#import <AppKit/AppKit.h>
#import <AudioToolbox/AudioToolbox.h>
#import <AudioUnit/AUCocoaUIView.h>
#import <WebKit/WebKit.h>
#import <objc/runtime.h>
#include <libproc.h>
#include <algorithm>
#include <chrono>
#include <cmath>
#include <csignal>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <functional>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>
#include <unistd.h>

#ifdef TRACK2STEM_STUDIO_DUO_PROBE
#include "audio/StudioAudioEngine.h"
#include "plugin_host/PluginFormats.h"
#include "plugin_host/PluginStateStore.h"
#include "project_io/ProjectFile.h"
int StudioDuoOriginalMain(int argc, char** argv);
#endif

static NSString* exportRoot;
static int exportMode = 0;
static __weak WKWebView* forcedLoadingView;
static IMP originalLoading = nullptr;

static BOOL ProbeLoading(id view, SEL selector) {
  if (view == forcedLoadingView) return YES;
  return reinterpret_cast<BOOL (*)(id, SEL)>(originalLoading)(view, selector);
}

@interface Track2stemProbeSavePanel : NSObject
@property(copy) NSString* title;
@property(copy) NSString* nameFieldStringValue;
@property BOOL canCreateDirectories;
- (NSInteger)runModal;
- (NSURL*)URL;
@end

@implementation Track2stemProbeSavePanel
- (NSInteger)runModal { return exportMode == 1 ? NSModalResponseCancel : NSModalResponseOK; }
- (NSURL*)URL {
  if (exportMode == 2) return [NSURL fileURLWithPath:exportRoot isDirectory:YES];
  return [NSURL fileURLWithPath:[exportRoot stringByAppendingPathComponent:self.nameFieldStringValue]];
}
@end

namespace {
struct LoadingExportScope {
  explicit LoadingExportScope(WKWebView* web) { forcedLoadingView = web; }
  ~LoadingExportScope() { forcedLoadingView = nil; }
};

void Require(bool condition, const char* message) {
  if (!condition) throw std::runtime_error(message);
}

#ifndef TRACK2STEM_STUDIO_DUO_PROBE
void Check(OSStatus status, const char* message) { Require(status == noErr, message); }
#endif

id ProbePanel(id, SEL) { return [[Track2stemProbeSavePanel alloc] init]; }

void Pump() {
#ifdef TRACK2STEM_STUDIO_DUO_PROBE
  juce::MessageManager::getInstance()->runDispatchLoopUntil(1);
#endif
  [[NSRunLoop currentRunLoop] runMode:NSDefaultRunLoopMode beforeDate:[NSDate dateWithTimeIntervalSinceNow:.01]];
}

bool Wait(const std::function<bool()>& condition, int seconds) {
  const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(seconds);
  while (std::chrono::steady_clock::now() < deadline) {
    if (condition()) return true;
    Pump();
  }
  return condition();
}

id JavaScript(WKWebView* web, NSString* source) {
  struct Result { bool done = false; __strong id value = nil; __strong NSError* failure = nil; };
  auto state = std::make_shared<Result>();
  [web evaluateJavaScript:source completionHandler:^(id result, NSError* error) {
    state->value = result;
    state->failure = error;
    state->done = true;
  }];
  Require(Wait([&] { return state->done; }, 10), "WebView JavaScript timed out");
  if (state->failure) std::fprintf(stderr, "WebView: %s\n", state->failure.localizedDescription.UTF8String);
  Require(state->failure == nil, "WebView JavaScript failed");
  return state->value;
}

bool HasText(WKWebView* web, NSString* text) {
  NSData* encoded = [NSJSONSerialization dataWithJSONObject:@[text] options:0 error:nil];
  NSString* literal = [[NSString alloc] initWithData:encoded encoding:NSUTF8StringEncoding];
  return [JavaScript(web, [NSString stringWithFormat:@"document.body.innerText.includes(%@[0])", literal]) boolValue];
}

WKWebView* FindWeb(NSView* parent) {
  if ([parent isKindOfClass:[WKWebView class]]) return (WKWebView*)parent;
  for (NSView* child in parent.subviews) if (WKWebView* result = FindWeb(child)) return result;
  return nil;
}

void WaitForNativeUI(WKWebView* web, const std::function<void()>& render) {
  const bool ready = Wait([&] {
    render();
    return [JavaScript(web, @"Boolean(typeof window.track2stemHost?.apiBase === 'string' && document.querySelector('h1')?.textContent.includes('Separate audio'))") boolValue];
  }, 45);
  if (!ready) {
    std::fprintf(stderr, "Native UI URL: %s\n", web.URL.absoluteString.UTF8String);
    std::fprintf(stderr, "Native UI body: %s\n", [[JavaScript(web, @"document.body.innerText") description] UTF8String]);
  }
  Require(ready, "The bundled worker and native UI bridge did not become ready");
}

#ifdef TRACK2STEM_STUDIO_DUO_PROBE
#include "StudioDuoAdapter.h"

IMP originalWindowOrder = nullptr;
void OffscreenWindowOrder(id window, SEL selector, NSWindowOrderingMode mode, NSInteger relative) {
  if (mode == NSWindowOut)
    reinterpret_cast<void (*)(id, SEL, NSWindowOrderingMode, NSInteger)>(originalWindowOrder)(window, selector, mode, relative);
}
#else
using HostComponent = AudioComponent;
using SavedState = NSDictionary*;

struct Audio {
  float left[256], right[256];
  double sampleTime = 0;
  double maximumRenderMicros = 0;
  Audio() {
    for (int index = 0; index < 256; ++index) {
      left[index] = .2f * std::sin(index * .07f);
      right[index] = .15f * std::cos(index * .09f);
    }
  }
  static OSStatus Input(void* context, AudioUnitRenderActionFlags*, const AudioTimeStamp*, UInt32, UInt32 frames, AudioBufferList* data) {
    auto& audio = *static_cast<Audio*>(context);
    if (frames != 256 || data->mNumberBuffers != 2) return kAudioUnitErr_TooManyFramesToProcess;
    data->mBuffers[0].mData = audio.left;
    data->mBuffers[1].mData = audio.right;
    for (UInt32 channel = 0; channel < 2; ++channel) {
      data->mBuffers[channel].mDataByteSize = sizeof(audio.left);
      data->mBuffers[channel].mNumberChannels = 1;
    }
    return noErr;
  }
  void Render(AudioUnit unit) {
    struct Buffers { UInt32 count; AudioBuffer buffers[2]; } output;
    float first[256] {}, second[256] {};
    output.count = 2;
    output.buffers[0] = {1, sizeof(first), first};
    output.buffers[1] = {1, sizeof(second), second};
    AudioTimeStamp timestamp {};
    timestamp.mSampleTime = sampleTime;
    timestamp.mFlags = kAudioTimeStampSampleTimeValid;
    AudioUnitRenderActionFlags flags = 0;
    const auto start = std::chrono::steady_clock::now();
    Check(AudioUnitRender(unit, &flags, &timestamp, 0, 256, reinterpret_cast<AudioBufferList*>(&output)), "Audio Unit render failed");
    maximumRenderMicros = std::max(maximumRenderMicros,
      std::chrono::duration<double, std::micro>(std::chrono::steady_clock::now() - start).count());
    sampleTime += 256;
    for (int index = 0; index < 256; ++index)
      Require(std::abs(first[index] - left[index]) < 1e-6 && std::abs(second[index] - right[index]) < 1e-6,
              "Offline separation changed the live pass-through audio");
  }
};

struct Instance {
  AudioUnit unit = nullptr;
  __strong NSWindow* window = nil;
  ~Instance() {
    if (window) {
      window.contentView = [[NSView alloc] init];
      [window close];
    }
    if (unit) {
      AudioUnitUninitialize(unit);
      AudioComponentInstanceDispose(unit);
    }
  }
};

WKWebView* Open(Instance& instance, HostComponent component, Audio& audio, SavedState saved = nil) {
  Check(AudioComponentInstanceNew(component, &instance.unit), "Cannot instantiate the real Audio Unit");
  const AudioStreamBasicDescription format {48000, kAudioFormatLinearPCM,
    kAudioFormatFlagsNativeFloatPacked | kAudioFormatFlagIsNonInterleaved,
    sizeof(float), 1, sizeof(float), 2, 32, 0};
  Check(AudioUnitSetProperty(instance.unit, kAudioUnitProperty_StreamFormat, kAudioUnitScope_Input, 0, &format, sizeof(format)), "Cannot set input format");
  Check(AudioUnitSetProperty(instance.unit, kAudioUnitProperty_StreamFormat, kAudioUnitScope_Output, 0, &format, sizeof(format)), "Cannot set output format");
  const AURenderCallbackStruct callback {Audio::Input, &audio};
  Check(AudioUnitSetProperty(instance.unit, kAudioUnitProperty_SetRenderCallback, kAudioUnitScope_Input, 0, &callback, sizeof(callback)), "Cannot attach the synthetic input");
  if (saved) {
    CFPropertyListRef state = (__bridge CFPropertyListRef)saved;
    Check(AudioUnitSetProperty(instance.unit, kAudioUnitProperty_ClassInfo, kAudioUnitScope_Global, 0, &state, sizeof(state)), "Cannot restore DAW project state");
  }
  Check(AudioUnitInitialize(instance.unit), "Cannot initialize the Audio Unit");
  UInt32 size = 0;
  Check(AudioUnitGetPropertyInfo(instance.unit, kAudioUnitProperty_CocoaUI, kAudioUnitScope_Global, 0, &size, nullptr), "The Audio Unit has no Cocoa editor");
  std::vector<uint8_t> storage(size);
  auto* information = reinterpret_cast<AudioUnitCocoaViewInfo*>(storage.data());
  Check(AudioUnitGetProperty(instance.unit, kAudioUnitProperty_CocoaUI, kAudioUnitScope_Global, 0, information, &size), "Cannot read editor information");
  NSBundle* viewBundle = [NSBundle bundleWithURL:(__bridge NSURL*)information->mCocoaAUViewBundleLocation];
  Require([viewBundle load], "Cannot load the real editor bundle");
  Class factoryClass = [viewBundle classNamed:(__bridge NSString*)information->mCocoaAUViewClass[0]];
  id<AUCocoaUIBase> factory = [[factoryClass alloc] init];
  NSView* view = [factory uiViewForAudioUnit:instance.unit withSize:NSMakeSize(1100, 760)];
  Require(view != nil, "The real editor did not create its view");
  instance.window = [[NSWindow alloc] initWithContentRect:NSMakeRect(0, 0, 1100, 760)
      styleMask:NSWindowStyleMaskBorderless backing:NSBackingStoreBuffered defer:NO];
  instance.window.releasedWhenClosed = NO;
  instance.window.contentView = view;
  WKWebView* web = FindWeb(view);
  Require(web != nil, "The shared WebView was not embedded");
  WaitForNativeUI(web, [&] { audio.Render(instance.unit); });
  return web;
}

SavedState SaveState(Instance& instance) {
  CFPropertyListRef state = nullptr;
  UInt32 size = sizeof(state);
  Check(AudioUnitGetProperty(instance.unit, kAudioUnitProperty_ClassInfo, kAudioUnitScope_Global, 0, &state, &size),
        "Cannot save the actual DAW state");
  return CFBridgingRelease(state);
}
#endif

void SelectFile(WKWebView* web, NSData* audio, NSString* name, int repeats = 1) {
  NSString* base64 = [audio base64EncodedStringWithOptions:0];
  NSString* script = [NSString stringWithFormat:
    @"(()=>{const original=Uint8Array.from(atob('%@'),c=>c.charCodeAt(0));"
     "const frames=original.length-44;const bytes=new Uint8Array(44+frames*%d);bytes.set(original.subarray(0,44));"
     "for(let i=0;i<%d;i++)bytes.set(original.subarray(44),44+i*frames);"
     "const header=new DataView(bytes.buffer);header.setUint32(4,bytes.length-8,true);header.setUint32(40,bytes.length-44,true);"
     "const input=document.querySelector('#file-input');const transfer=new DataTransfer();"
     "transfer.items.add(new File([bytes],'%@',{type:'audio/wav'}));input.files=transfer.files;"
     "input.dispatchEvent(new Event('change',{bubbles:true}));return true;})()", base64, repeats, repeats, name];
  JavaScript(web, script);
  Require(Wait([&] { return [JavaScript(web, @"!document.querySelector('.upload-button').disabled") boolValue]; }, 5), "Synthetic file selection was not accepted");
}

pid_t OwnedWorker(const char* executable) {
  pid_t children[1024] {};
  const int count = proc_listchildpids(getpid(), children, sizeof(children));
  for (int index = 0; index < count; ++index) {
    char path[PROC_PIDPATHINFO_MAXSIZE] {};
    if (proc_pidpath(children[index], path, sizeof(path)) > 0 &&
        std::strcmp(path, executable) == 0 && getpgid(children[index]) == children[index]) return children[index];
  }
  return 0;
}
}

int main(int argc, char** argv) {
#ifdef TRACK2STEM_STUDIO_DUO_PROBE
  if (argc < 2 || std::strcmp(argv[1], "--track2stem-native-workflow") != 0)
    return StudioDuoOriginalMain(argc, argv);
  --argc;
  ++argv;
  juce::ScopedJuceInitialiser_GUI juceInitialiser;
#endif
  if (argc != 6) {
    std::fprintf(stderr, "Usage: native-smoke component worker models new-data-directory synthetic-wav\n");
    return 2;
  }
  @autoreleasepool {
    try {
      setenv("TRACK2STEM_WORKER", argv[2], 1);
      setenv("TRACK2STEM_MODELS_DIR", argv[3], 1);
      setenv("TRACK2STEM_DATA_DIR", argv[4], 1);
      NSString* directory = [NSString stringWithUTF8String:argv[4]];
      Require(![[NSFileManager defaultManager] fileExistsAtPath:directory], "Evidence directory already exists");
      [[NSFileManager defaultManager] createDirectoryAtPath:directory withIntermediateDirectories:YES attributes:nil error:nil];
      exportRoot = [directory stringByAppendingPathComponent:@"exports"];
      [[NSFileManager defaultManager] createDirectoryAtPath:exportRoot withIntermediateDirectories:YES attributes:nil error:nil];
      [NSApplication sharedApplication];
      [NSApp setActivationPolicy:NSApplicationActivationPolicyProhibited];
      [NSApp finishLaunching];
#ifdef TRACK2STEM_STUDIO_DUO_PROBE
      Method ordering = class_getInstanceMethod([NSWindow class], @selector(orderWindow:relativeTo:));
      originalWindowOrder = method_setImplementation(ordering, reinterpret_cast<IMP>(OffscreenWindowOrder));
#endif
      Method panel = class_getClassMethod([NSSavePanel class], @selector(savePanel));
      method_setImplementation(panel, reinterpret_cast<IMP>(ProbePanel));
      Method loading = class_getInstanceMethod([WKWebView class], @selector(isLoading));
      originalLoading = method_setImplementation(loading, reinterpret_cast<IMP>(ProbeLoading));
#ifdef TRACK2STEM_STUDIO_DUO_PROBE
      HostComponent component = CreateComponent(argv[1], argv[5], argv[4]);
#else
      NSBundle* bundle = [NSBundle bundleWithPath:[NSString stringWithUTF8String:argv[1]]];
      Require([bundle load], "Cannot load the explicit AU bundle");
      CFBundleRef nativeBundle = CFBundleCreate(kCFAllocatorDefault, (__bridge CFURLRef)bundle.bundleURL);
      Require(nativeBundle != nullptr && CFBundleLoadExecutable(nativeBundle), "Cannot retain the AU factory bundle");
      const auto factory = reinterpret_cast<AudioComponentFactoryFunction>(
        CFBundleGetFunctionPointerForName(nativeBundle, CFSTR("Track2stem_Factory")));
      Require(factory != nullptr, "The AU factory symbol is missing");
      const AudioComponentDescription description {kAudioUnitType_Effect, 'T2St', 'T2Sm', 0, 0};
      HostComponent component = AudioComponentRegister(&description, CFSTR("Track2stem: Track2stem"), 256, factory);
      Require(component != nullptr, "Cannot register the explicit AU factory");
#endif
      NSString* fixturePath = [NSString stringWithUTF8String:argv[5]];
      Require(fixturePath != nil, "The generated WAV fixture path is not valid UTF-8");
      NSData* source = [NSData dataWithContentsOfFile:fixturePath];
      Require(source.length > 44, "The generated WAV fixture is missing");
      SavedState saved {};
      Audio audio;
      {
        Instance first;
        WKWebView* web = Open(first, component, audio);
        JavaScript(web, @"document.querySelector('input[name=outputFormat][value=wav]').click()");
        SelectFile(web, source, @"native-demo.wav");
        JavaScript(web, @"document.querySelector('.upload-button').click()");
        Require(Wait([&] { audio.Render(first.unit); return HasText(web, @"Separation complete"); }, 90), "Native import/separation did not complete");
        {
          LoadingExportScope loadingExport(web);
          JavaScript(web, @"document.querySelector('button[aria-label=\"Download bass\"]').click()");
          const bool exportFinished = Wait([&] { audio.Render(first.unit); return HasText(web, @"File exported."); }, 15);
          if (!exportFinished)
            std::fprintf(stderr, "Export UI loading=%d body=%s\n", static_cast<int>([web isLoading]),
                         [[JavaScript(web, @"document.body.innerText") description] UTF8String]);
          Require(exportFinished, "Native export did not finish through the OS download adapter");
        }
        NSArray* files = [[NSFileManager defaultManager] contentsOfDirectoryAtPath:exportRoot error:nil];
        Require(files.count == 1, "Native export did not create exactly one owned file");
        NSData* exported = [NSData dataWithContentsOfFile:[exportRoot stringByAppendingPathComponent:files[0]]];
        Require(exported.length > 44 && std::memcmp(exported.bytes, "RIFF", 4) == 0, "Native export is not a real WAV");
#ifdef TRACK2STEM_STUDIO_DUO_PROBE
        first.unit->pause();
        audio.reference->pause();
#endif
        JavaScript(web, @"window.__probeExportCompletions=0;window.addEventListener('track2stem-native-message',event=>{"
                        "if(event.detail.type==='native_notice'&&event.detail.message==='File exported.')window.__probeExportCompletions++;});null");
        {
          LoadingExportScope loadingExport(web);
          JavaScript(web, @"document.querySelector('button[aria-label=\"Download drums\"]').click()");
          Require(Wait([&] { return [JavaScript(web, @"window.__probeExportCompletions>0") boolValue]; }, 15),
                  "Native export completion depended on transport/audio callbacks");
        }
#ifdef TRACK2STEM_STUDIO_DUO_PROBE
        first.unit->play();
        audio.reference->play();
#endif
        exportMode = 1;
        JavaScript(web, @"document.querySelector('button[aria-label=\"Download bass\"]').click()");
        Require(Wait([&] { return HasText(web, @"Export cancelled."); }, 15), "Cancelled native export did not report cancellation");
        exportMode = 2;
        JavaScript(web, @"document.querySelector('button[aria-label=\"Download bass\"]').click()");
        Require(Wait([&] { return HasText(web, @"Export failed."); }, 15), "Native export failure was not surfaced");
        saved = SaveState(first);
      }
      {
        Instance reopened;
        audio.sampleTime = 0;
        WKWebView* web = Open(reopened, component, audio, saved);
        Require(Wait([&] { return HasText(web, @"Separation complete"); }, 15), "Saved processed-audio references did not restore");
        Require([JavaScript(web, @"document.querySelector('input[name=outputFormat][value=wav]').checked") boolValue], "Saved output settings did not restore");
        NSString* cached = JavaScript(web, @"JSON.parse(window.track2stemHost.storage.getItem('track2stem_current_job')).output_files.bass");
        Require([cached hasPrefix:[directory stringByAppendingString:@"/outputs/"]], "Cache failure probe must stay inside its owned output directory");
        NSString* backup = [cached stringByAppendingString:@".probe-backup"];
        Require([[NSFileManager defaultManager] moveItemAtPath:cached toPath:backup error:nil], "Cannot stage the owned missing-file probe");
        JavaScript(web, @"document.querySelector('button[aria-label=\"Download bass\"]').click()");
        Require(Wait([&] { return HasText(web, @"Export failed."); }, 15), "A missing cached stem was falsely reported as an exported file");
        Require([[NSFileManager defaultManager] moveItemAtPath:backup toPath:cached error:nil], "Cannot restore the owned cached stem");
        NSMutableData* corrupt = [NSMutableData dataWithLength:128];
        auto* bytes = static_cast<uint8_t*>(corrupt.mutableBytes);
        std::memcpy(bytes, "RIFF", 4);
        std::memcpy(bytes + 8, "WAVEfmt ", 8);
        SelectFile(web, corrupt, @"native-invalid.wav");
        JavaScript(web, @"document.querySelector('.upload-button').click()");
        Require(Wait([&] {
          audio.Render(reopened.unit);
          return [JavaScript(web, @"JSON.parse(window.track2stemHost.storage.getItem('track2stem_current_job'))?.status==='failed'") boolValue];
        }, 30), "Malformed native audio did not produce a failed processing state");
        Require([JavaScript(web, @"document.body.innerText.toLowerCase().includes('failed')") boolValue],
                "The native processing failure was not visible in the editor");
        SelectFile(web, source, @"native-long.wav", 20);
        JavaScript(web, @"document.querySelector('.upload-button').click()");
        Require(Wait([&] { audio.Render(reopened.unit); return HasText(web, @"Cancel job"); }, 10), "The running native job cannot be cancelled");
        NSString* cancelledJob = JavaScript(web, @"JSON.parse(window.track2stemHost.storage.getItem('track2stem_current_job')).id");
        JavaScript(web, @"Array.from(document.querySelectorAll('button')).find(button=>button.textContent==='Cancel job').click()");
        Require(Wait([&] {
          audio.Render(reopened.unit);
          return [JavaScript(web, @"window.track2stemHost.storage.getItem('track2stem_current_job')===null") boolValue] && !HasText(web, @"Cancel job");
        }, 15), "Native cancellation did not clear the running job");
        NSString* cancelledUpload = [[directory stringByAppendingPathComponent:@"uploads"] stringByAppendingPathComponent:cancelledJob];
        Require(Wait([&] { audio.Render(reopened.unit); return ![[NSFileManager defaultManager] fileExistsAtPath:cancelledUpload]; }, 30),
                "Cancelled native processing did not release its owned upload");
        SelectFile(web, source, @"native-crash.wav", 20);
        JavaScript(web, @"document.querySelector('.upload-button').click()");
        Require(Wait([&] { audio.Render(reopened.unit); return HasText(web, @"Cancel job"); }, 10), "The crash-recovery job did not start");
        const pid_t worker = OwnedWorker(argv[2]);
        Require(worker > 0, "Cannot identify only the owned worker process group");
        Require(kill(-worker, SIGKILL) == 0, "Cannot inject the owned worker failure");
        Require(Wait([&] { audio.Render(reopened.unit); return HasText(web, @"Local worker unavailable"); }, 10), "Worker failure did not produce an actionable native error");
        JavaScript(web, @"document.querySelector('button').click()");
        Require(Wait([&] { audio.Render(reopened.unit); return HasText(web, @"Processed audio is missing or this job was interrupted"); }, 45), "Restart did not preserve the interrupted-job recovery policy");
      }
      Require(Wait([&] { return OwnedWorker(argv[2]) == 0; }, 5), "Plugin removal left an owned worker running");
#ifdef TRACK2STEM_STUDIO_DUO_PROBE
      Require(audio.audibleBlocks > 10, "The Studio Duo workflow did not exercise audible generated playback");
      std::printf("{\"host\":\"Studio Duo %s\",\"format\":\"%s\",\"mode\":\"trustedInProcess\","
                  "\"project_package_roundtrip\":true,\"audible_playback_blocks\":%d}\n",
                  STUDIO_DUO_VERSION, component.description.pluginFormatName.toRawUTF8(), audio.audibleBlocks);
#endif
      std::printf("{\"status\":\"pass\",\"audio_device_opened\":false,\"native_import_export\":true,"
                  "\"save_restore\":true,\"processing_cancellation\":true,\"missing_resource_failure\":true,"
                  "\"failed_processing\":true,\"paused_export\":true,\"loading_export_status\":true,"
                  "\"worker_crash_recovery\":true,\"worker_teardown\":true,\"maximum_render_microseconds\":%.3f}\n",
                  audio.maximumRenderMicros);
      return 0;
    } catch (const std::exception& error) {
      std::fprintf(stderr, "Native smoke failure: %s\n", error.what());
      return 1;
    }
  }
}
