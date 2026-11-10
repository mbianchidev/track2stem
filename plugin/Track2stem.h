#pragma once

#include "IPlug_include_in_plug_hdr.h"
#include "WorkerClient.h"
#include <mutex>
#include <string>

class Track2stem final : public iplug::Plugin {
public:
  explicit Track2stem(const iplug::InstanceInfo& info);
  ~Track2stem() override;
  void ProcessBlock(iplug::sample** inputs, iplug::sample** outputs, int frames) override;
  void OnIdle() override;
  void OnUIOpen() override;
  void OnUIClose() override;
  void OnWebViewReady() override {}
  bool OnMessage(int tag, int control, int size, const void* data) override;
  void OnMessageFromWebView(const char* message) override;
  bool SerializeState(iplug::IByteChunk& chunk) const override;
  int UnserializeState(const iplug::IByteChunk& chunk, int offset) override;
  bool OnCanNavigateToURL(const char* url) override;
  bool OnCanDownloadMIMEType(const char* mimeType) override;
  void OnGetLocalDownloadPathForFile(const char* filename, WDL_String& path) override;
  void OnDownloadedFile(const char* path) override;
  void OnFailedToDownloadFile(const char* path) override;

private:
  void SendHostState();
  void ShowStartup(bool failed = false);
  WorkerClient mWorker;
  NativePaths mPaths;
  std::string mAPIBase;
  std::string mUIURL;
  mutable std::mutex mStateMutex;
  std::string mProjectState = R"({"version":1,"storage":{}})";
  bool mEditorOpen = false;
  bool mExportCancelled = false;
  std::atomic<bool> mRestorePending {false};
  bool mStartRequested = false;
  bool mFrontendReady = false;
  uint64_t mHostGeneration = 0;
};
