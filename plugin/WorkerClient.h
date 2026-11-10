#pragma once

#include <atomic>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

struct NativePaths {
  std::string worker;
  std::string root;
  std::string models;
  std::string ui;
};

NativePaths GetNativePaths(const char* bundleID);
std::string ChooseExportPath(const char* filename);
bool OpenDocumentation(const char* url);

class WorkerClient {
public:
  ~WorkerClient();
  void Start(const NativePaths& paths);
  void Stop();
  bool Running() const { return mRunning.load(); }
  std::vector<std::string> Drain();

private:
  void Run(NativePaths paths);
  void Push(std::string message);
  void Error(const std::string& message);
  std::atomic<bool> mRunning {false};
  std::atomic<bool> mStopping {false};
  std::thread mThread;
  std::mutex mMutex;
  std::vector<std::string> mMessages;
};
