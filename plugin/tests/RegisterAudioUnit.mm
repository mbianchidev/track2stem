#import <Foundation/Foundation.h>
#import <AudioToolbox/AudioToolbox.h>
#include <cstdio>
#include <cstdlib>

namespace {
CFBundleRef componentBundle = nullptr;

__attribute__((constructor))
void RegisterOwnedTestComponent() {
  const char* path = std::getenv("TRACK2STEM_AU_BUNDLE");
  if (!path) return;
  unsetenv("DYLD_INSERT_LIBRARIES");
  @autoreleasepool {
    NSURL* url = [NSURL fileURLWithPath:[NSString stringWithUTF8String:path]];
    componentBundle = CFBundleCreate(kCFAllocatorDefault, (__bridge CFURLRef)url);
    if (!componentBundle || !CFBundleLoadExecutable(componentBundle)) {
      std::fprintf(stderr, "Track2stem probe: could not load the explicit AU bundle\n");
      std::exit(2);
    }
    const auto factory = reinterpret_cast<AudioComponentFactoryFunction>(
        CFBundleGetFunctionPointerForName(componentBundle, CFSTR("Track2stem_Factory")));
    const AudioComponentDescription description {kAudioUnitType_Effect, 'T2St', 'T2Sm', 0, 0};
    if (!factory || !AudioComponentRegister(&description, CFSTR("Track2stem: Track2stem"), 256, factory)) {
      std::fprintf(stderr, "Track2stem probe: process-local AU registration failed\n");
      std::exit(2);
    }
  }
}
}
