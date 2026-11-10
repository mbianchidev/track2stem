#include "Track2stem.h"
#include "IPlug_include_in_plug_src.h"
#include "json.hpp"
#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <cstring>

namespace {
constexpr int kHello = 100;
constexpr int kStoreState = 101;
constexpr int kRestart = 102;
constexpr uint32_t kStateVersion = 1;
constexpr uint32_t kMaximumState = 8 * 1024 * 1024;

bool ValidState(const nlohmann::json& state) {
  if (!state.is_object() || !state.contains("version") || state["version"] != 1
      || !state.contains("storage") || !state["storage"].is_object()) return false;
  for (const auto& entry : state["storage"].items())
    if (entry.key().rfind("track2stem_", 0) != 0 || !entry.value().is_string()) return false;
  return true;
}
}

Track2stem::Track2stem(const iplug::InstanceInfo& info)
  : iplug::Plugin(info, iplug::MakeConfig(0, 1)) {
  MakePreset("Default");
  SetMaxJSStringLength(12 * 1024 * 1024);
  mEditorInitFunc = [this]() {
    mPaths = GetNativePaths(GetBundleID());
    mFrontendReady = false;
    if (!mUIURL.empty() && mWorker.Running()) LoadURL(mUIURL.c_str());
    else ShowStartup();
  };
}

Track2stem::~Track2stem() { mWorker.Stop(); }

void Track2stem::ProcessBlock(iplug::sample** inputs, iplug::sample** outputs, int frames) {
  const int inputCount = NInChansConnected();
  for (int channel = 0; channel < NOutChansConnected(); ++channel) {
    if (inputCount > 0)
      std::memmove(outputs[channel], inputs[std::min(channel, inputCount - 1)], frames * sizeof(iplug::sample));
    else
      std::memset(outputs[channel], 0, frames * sizeof(iplug::sample));
  }
}

void Track2stem::ShowStartup(bool failed) {
  mFrontendReady = false;
  LoadHTML(failed
    ? "<html><head><script>window.SAMFD=function(){return null;}</script></head><body style='background:#15171a;color:#f4f5f7;font:16px system-ui;padding:40px'>"
      "<h1>Local worker unavailable</h1><p>Install the Track2stem runtime or check its logs. Existing audio is preserved.</p>"
      "<button onclick='IPlugSendMsg({msg:\"SAMFUI\",msgTag:102,ctrlTag:-1,data:0})'>Restart local worker</button></body></html>"
    : "<html><head><script>window.SAMFD=function(){return null;}</script></head><body style='background:#15171a;color:#f4f5f7;font:16px system-ui;padding:40px'>"
      "<h1>Track2stem</h1><p>Starting the local CPU worker...</p></body></html>");
}

void Track2stem::OnUIOpen() {
  mEditorOpen = true;
  if (!mStartRequested && !mWorker.Running() && mAPIBase.empty()) {
    std::fprintf(stderr, "Track2stem: starting the local CPU worker\n");
    mStartRequested = true;
    mWorker.Start(mPaths);
  }
}

void Track2stem::OnUIClose() {
  mEditorOpen = false;
  mFrontendReady = false;
}

void Track2stem::OnIdle() {
  for (const auto& line : mWorker.Drain()) {
    auto message = nlohmann::json::parse(line, nullptr, false);
    if (message.is_discarded() || !message.is_object()) continue;
    if (message.contains("type") && message["type"] == "ready"
        && message.contains("api_base") && message["api_base"].is_string()
        && message.contains("ui_url") && message["ui_url"].is_string()) {
      const auto base = message["api_base"].get<std::string>();
      const auto ui = message["ui_url"].get<std::string>();
      if (base.rfind("http://127.0.0.1:", 0) != 0 || ui.rfind("http://127.0.0.1:", 0) != 0) {
        std::fprintf(stderr, "Track2stem: refusing a non-local worker URL\n");
        if (mEditorOpen) ShowStartup(true);
        continue;
      }
      mAPIBase = base;
      mUIURL = ui;
      std::fprintf(stderr, "Track2stem: local worker ready\n");
      if (mEditorOpen) {
        mFrontendReady = false;
        LoadURL(mUIURL.c_str());
      }
    } else if (message.contains("type") && message["type"] == "worker_error") {
      mAPIBase.clear();
      mUIURL.clear();
      if (mEditorOpen) ShowStartup(true);
    }
  }
  if (mEditorOpen && mFrontendReady && !mAPIBase.empty() && mRestorePending.load()) {
    SendHostState();
  }
}

void Track2stem::SendHostState() {
  mRestorePending.store(false);
  nlohmann::json state;
  uint64_t generation;
  {
    std::lock_guard<std::mutex> guard(mStateMutex);
    state = nlohmann::json::parse(mProjectState, nullptr, false);
    generation = mHostGeneration;
  }
  if (!ValidState(state)) {
    SendJSONFromDelegate({{"type", "native_error"}, {"message", "The saved project state is invalid."}});
    return;
  }
  SendJSONFromDelegate({{"type", "host_ready"}, {"version", 1}, {"generation", generation},
                        {"api_base", mAPIBase}, {"state", state}});
}

bool Track2stem::OnMessage(int tag, int, int size, const void* data) {
  if (tag == kHello) {
    std::fprintf(stderr, "Track2stem: shared native UI connected\n");
    mFrontendReady = true;
    SendHostState();
    return true;
  }
  if (tag == kRestart) {
    mWorker.Stop();
    mAPIBase.clear();
    mUIURL.clear();
    ShowStartup();
    mWorker.Start(mPaths);
    return true;
  }
  if (tag != kStoreState || size <= 0 || size > static_cast<int>(kMaximumState) || !data) return false;
  std::string value(static_cast<const char*>(data), static_cast<size_t>(size));
  const auto state = nlohmann::json::parse(value, nullptr, false);
  if (!ValidState(state) || !state.contains("generation") || !state["generation"].is_number_integer()) {
    std::fprintf(stderr, "Track2stem: rejected invalid project storage\n");
    SendJSONFromDelegate({{"type", "native_error"}, {"message", "Project settings could not be saved: invalid state."}});
    return false;
  }
  {
    std::lock_guard<std::mutex> guard(mStateMutex);
    if (state["generation"] != mHostGeneration) return true;
    mProjectState = nlohmann::json({{"version", 1}, {"storage", state["storage"]}}).dump();
  }
#ifdef VST3_API
  Steinberg::FUnknownPtr<Steinberg::Vst::IComponentHandler2> handler(GetComponentHandler());
  if (handler && handler->setDirty(true) != Steinberg::kResultTrue)
    std::fprintf(stderr, "Track2stem: the host did not acknowledge changed project metadata; save explicitly\n");
#else
  InformHostOfPresetChange();
#endif
  return true;
}

void Track2stem::OnMessageFromWebView(const char* raw) {
  if (!raw || strnlen(raw, 12 * 1024 * 1024 + 1) > 12 * 1024 * 1024) return;
  const auto message = nlohmann::json::parse(raw, nullptr, false);
  if (!message.is_object() || message.is_discarded() || !message.contains("msg") || message["msg"] != "SAMFUI"
      || !message.contains("msgTag") || !message["msgTag"].is_number_integer()
      || !message.contains("ctrlTag") || !message["ctrlTag"].is_number_integer()
      || !message.contains("data")) return;
  if (message["msgTag"] < kHello || message["msgTag"] > kRestart || message["ctrlTag"] != -1) return;
  if (message["data"].is_string()) {
    const auto encoded = message["data"].get<std::string>();
    if (encoded.size() % 4 != 0 || encoded.size() > 12 * 1024 * 1024
        || encoded.find_first_not_of("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=") != std::string::npos) return;
  } else if (message["data"] != 0) return;
  iplug::WebViewEditorDelegate::OnMessageFromWebView(raw);
}

bool Track2stem::SerializeState(iplug::IByteChunk& chunk) const {
  std::lock_guard<std::mutex> guard(mStateMutex);
  const uint32_t length = static_cast<uint32_t>(mProjectState.size());
  chunk.Put(&kStateVersion);
  chunk.Put(&length);
  chunk.PutBytes(mProjectState.data(), static_cast<int>(length));
  return SerializeParams(chunk);
}

int Track2stem::UnserializeState(const iplug::IByteChunk& chunk, int offset) {
  uint32_t version = 0, length = 0;
  if (offset < 0 || offset > chunk.Size() - 8) return -1;
  offset = chunk.Get(&version, offset);
  offset = chunk.Get(&length, offset);
  if (version != kStateVersion || length > kMaximumState || offset < 0
      || length > static_cast<uint32_t>(chunk.Size() - offset)) {
    std::fprintf(stderr, "Track2stem: unsupported or truncated saved project state\n");
    return -1;
  }
  std::string value(length, '\0');
  offset = chunk.GetBytes(value.data(), static_cast<int>(length), offset);
  const auto state = nlohmann::json::parse(value, nullptr, false);
  if (!ValidState(state)) {
    std::fprintf(stderr, "Track2stem: invalid saved project settings\n");
    return -1;
  }
  {
    std::lock_guard<std::mutex> guard(mStateMutex);
    mProjectState = std::move(value);
    ++mHostGeneration;
  }
  mRestorePending.store(true);
  return UnserializeParams(chunk, offset);
}

bool Track2stem::OnCanNavigateToURL(const char* url) {
  const std::string target(url ? url : "");
  const std::string root = mAPIBase.empty() ? "" : mAPIBase.substr(0, mAPIBase.size() - 4);
  if (target == "about:blank") return true;
  if (!root.empty() && target.rfind(root + "/", 0) == 0) {
    if (target.rfind(mAPIBase + "/download/", 0) == 0 || target.rfind(mAPIBase + "/artifacts/", 0) == 0)
      mExportCancelled = false;
    return true;
  }
  if (target.rfind("https://github.com/mbianchidev/track2stem", 0) == 0 && !OpenDocumentation(url))
    SendJSONFromDelegate({{"type", "native_error"}, {"message", "Could not open the documentation link."}});
  return false;
}

bool Track2stem::OnCanDownloadMIMEType(const char* mimeType) {
  return std::strcmp(mimeType, "text/html") != 0;
}

void Track2stem::OnGetLocalDownloadPathForFile(const char* filename, WDL_String& path) {
  const auto selected = ChooseExportPath(filename);
  mExportCancelled = selected.empty();
  if (mExportCancelled)
    SendJSONFromDelegate({{"type", "native_notice"}, {"message", "Export cancelled."}});
  path.Set(selected.c_str());
}

void Track2stem::OnDownloadedFile(const char*) {
  SendJSONFromDelegate({{"type", "native_notice"}, {"message", "File exported."}});
}

void Track2stem::OnFailedToDownloadFile(const char*) {
  SendJSONFromDelegate({{"type", mExportCancelled ? "native_notice" : "native_error"},
                        {"message", mExportCancelled ? "Export cancelled." : "Export failed. Choose a writable destination and retry."}});
}
