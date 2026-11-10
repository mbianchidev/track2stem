#import <Cocoa/Cocoa.h>

#include "WorkerClient.h"
#include "json.hpp"
#include <cerrno>
#include <chrono>
#include <csignal>
#include <cstdio>
#include <cstring>
#include <fcntl.h>
#include <filesystem>
#include <poll.h>
#include <spawn.h>
#include <sys/wait.h>
#include <unistd.h>

extern char** environ;

namespace {
std::string EnvironmentOr(const char* name, const std::string& fallback) {
  const char* value = std::getenv(name);
  return value && *value ? value : fallback;
}
}

NativePaths GetNativePaths(const char* bundleID) {
  @autoreleasepool {
    NSBundle* bundle = [NSBundle bundleWithIdentifier:[NSString stringWithUTF8String:bundleID]];
    if (!bundle.resourcePath)
      std::fprintf(stderr, "Track2stem: cannot locate resources for bundle %s\n", bundleID);
    const std::string resources = bundle.resourcePath ? bundle.resourcePath.UTF8String : "";
    const std::string home = NSHomeDirectory().UTF8String;
    return {
      EnvironmentOr("TRACK2STEM_WORKER", home + "/Library/Application Support/Track2stem/Runtime/track2stem-worker"),
      EnvironmentOr("TRACK2STEM_DATA_DIR", home + "/Library/Application Support/Track2stem/Data"),
      EnvironmentOr("TRACK2STEM_MODELS_DIR", home + "/Library/Caches/Track2stem/models"),
      resources + "/web"
    };
  }
}

std::string ChooseExportPath(const char* filename) {
  NSSavePanel* panel = [NSSavePanel savePanel];
  panel.title = @"Export Track2stem file";
  panel.nameFieldStringValue = [NSString stringWithUTF8String:filename];
  panel.canCreateDirectories = YES;
  if ([panel runModal] != NSModalResponseOK) return {};
  return panel.URL.fileSystemRepresentation;
}

bool OpenDocumentation(const char* url) {
  return [[NSWorkspace sharedWorkspace] openURL:[NSURL URLWithString:[NSString stringWithUTF8String:url]]];
}

WorkerClient::~WorkerClient() { Stop(); }

void WorkerClient::Start(const NativePaths& paths) {
  if (mRunning.load()) return;
  if (mThread.joinable()) mThread.join();
  mStopping.store(false);
  mRunning.store(true);
  mThread = std::thread(&WorkerClient::Run, this, paths);
}

void WorkerClient::Stop() {
  mStopping.store(true);
  if (mThread.joinable()) mThread.join();
}

void WorkerClient::Push(std::string message) {
  std::lock_guard<std::mutex> guard(mMutex);
  mMessages.push_back(std::move(message));
}

void WorkerClient::Error(const std::string& message) {
  std::fprintf(stderr, "Track2stem worker: %s\n", message.c_str());
  Push(nlohmann::json({{"version", 1}, {"type", "worker_error"}, {"message", message}}).dump());
}

std::vector<std::string> WorkerClient::Drain() {
  std::lock_guard<std::mutex> guard(mMutex);
  std::vector<std::string> result;
  result.swap(mMessages);
  return result;
}

void WorkerClient::Run(NativePaths paths) {
  std::error_code directoryError;
  std::filesystem::create_directories(paths.root, directoryError);
  if (directoryError) {
    Error("Cannot create the local data directory: " + directoryError.message());
    mRunning.store(false);
    return;
  }
  int descriptors[2];
  if (pipe(descriptors) != 0) {
    Error(std::string("Cannot create worker pipe: ") + std::strerror(errno));
    mRunning.store(false);
    return;
  }
  posix_spawn_file_actions_t actions;
  posix_spawnattr_t attributes;
  int status = posix_spawn_file_actions_init(&actions);
  if (status != 0) {
    close(descriptors[0]);
    close(descriptors[1]);
    Error(std::string("Cannot initialize worker launch: ") + std::strerror(status));
    mRunning.store(false);
    return;
  }
  status = posix_spawnattr_init(&attributes);
  if (status != 0) {
    posix_spawn_file_actions_destroy(&actions);
    close(descriptors[0]);
    close(descriptors[1]);
    Error(std::string("Cannot initialize worker process group: ") + std::strerror(status));
    mRunning.store(false);
    return;
  }
  status = posix_spawn_file_actions_adddup2(&actions, descriptors[1], STDOUT_FILENO);
  if (status == 0) status = posix_spawn_file_actions_addclose(&actions, descriptors[0]);
  if (status == 0) status = posix_spawn_file_actions_addclose(&actions, descriptors[1]);
  if (status == 0) status = posix_spawn_file_actions_addopen(&actions, STDIN_FILENO, "/dev/null", O_RDONLY, 0);
  const std::string log = paths.root + "/worker-" + std::to_string(getpid()) + ".log";
  if (status == 0) status = posix_spawn_file_actions_addopen(&actions, STDERR_FILENO, log.c_str(), O_WRONLY | O_APPEND | O_CREAT, 0600);
  if (status == 0) status = posix_spawnattr_setflags(&attributes, POSIX_SPAWN_SETPGROUP | POSIX_SPAWN_CLOEXEC_DEFAULT);
  if (status == 0) status = posix_spawnattr_setpgroup(&attributes, 0);
  std::vector<std::string> values = {paths.worker, "--root", paths.root, "--models", paths.models,
                                     "--ui", paths.ui, "--serve"};
  std::vector<char*> arguments;
  for (auto& value : values) arguments.push_back(value.data());
  arguments.push_back(nullptr);
  pid_t pid = 0;
  if (status == 0) status = posix_spawn(&pid, paths.worker.c_str(), &actions, &attributes, arguments.data(), environ);
  posix_spawn_file_actions_destroy(&actions);
  posix_spawnattr_destroy(&attributes);
  close(descriptors[1]);
  if (status != 0) {
    close(descriptors[0]);
    Error(std::string("Cannot start the bundled local worker. Install the Track2stem runtime, then reopen the plugin. ") + std::strerror(status));
    mRunning.store(false);
    return;
  }
  std::string pending;
  int exitStatus = 0;
  bool reaped = false;
  const auto startupDeadline = std::chrono::steady_clock::now() + std::chrono::seconds(30);
  bool ready = false;
  while (!mStopping.load()) {
    pollfd descriptor {descriptors[0], POLLIN, 0};
    const int available = poll(&descriptor, 1, 100);
    if (available < 0 && errno != EINTR) {
      Error(std::string("Cannot read local worker: ") + std::strerror(errno));
      break;
    }
    if (available > 0 && descriptor.revents & POLLIN) {
      char buffer[4096];
      const auto count = read(descriptors[0], buffer, sizeof(buffer));
      if (count > 0) pending.append(buffer, static_cast<size_t>(count));
      if (pending.size() > 65536) {
        Error("Local worker emitted an oversized protocol response");
        break;
      }
      size_t delimiter;
      while ((delimiter = pending.find('\n')) != std::string::npos) {
        std::string line = pending.substr(0, delimiter);
        pending.erase(0, delimiter + 1);
        auto message = nlohmann::json::parse(line, nullptr, false);
        if (message.is_discarded() || !message.is_object()
            || !message.contains("version") || message["version"] != 1) {
          Error("Local worker emitted an incompatible response");
          continue;
        }
        if (message.contains("type") && message["type"] == "ready") ready = true;
        Push(std::move(line));
      }
    }
    const pid_t result = waitpid(pid, &exitStatus, WNOHANG);
    if (result == pid) {
      reaped = true;
      Error("The local worker stopped. Existing audio is preserved; reopen the plugin or restart its worker.");
      break;
    }
    if (available > 0 && descriptor.revents & (POLLERR | POLLNVAL | POLLHUP) && !(descriptor.revents & POLLIN)) {
      Error("The local worker status channel closed unexpectedly");
      break;
    }
    if (!ready && std::chrono::steady_clock::now() > startupDeadline) {
      Error("The local worker did not become ready within 30 seconds. Check its runtime installation.");
      break;
    }
  }
  if (!reaped) {
    if (kill(-pid, SIGTERM) != 0 && errno != ESRCH)
      std::fprintf(stderr, "Track2stem: cannot stop owned worker: %s\n", std::strerror(errno));
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(2);
    while (std::chrono::steady_clock::now() < deadline) {
      if (waitpid(pid, &exitStatus, WNOHANG) == pid) { reaped = true; break; }
      std::this_thread::sleep_for(std::chrono::milliseconds(20));
    }
    if (!reaped) {
      if (kill(-pid, SIGKILL) != 0 && errno != ESRCH)
        std::fprintf(stderr, "Track2stem: cannot kill owned worker: %s\n", std::strerror(errno));
      while (waitpid(pid, &exitStatus, 0) < 0 && errno == EINTR) {}
    }
  }
  close(descriptors[0]);
  mRunning.store(false);
}
