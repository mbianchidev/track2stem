struct HostComponent {
  juce::PluginDescription description;
  juce::File fixture;
  juce::File evidence;
};

using SavedState = juce::File;

struct Audio {
  std::unique_ptr<studio::StudioAudioEngine> reference;
  double sampleTime = 0;
  double maximumRenderMicros = 0;
  int audibleBlocks = 0;

  void Configure(studio::Project project) {
    for (auto& track : project.tracks) track.inserts.clear();
    reference = std::make_unique<studio::StudioAudioEngine>();
    Require(reference->configureAudioForTesting(48000, 256).wasOk(), "Cannot configure the real Studio Duo reference engine");
    const auto prepared = reference->updateProject(project);
    Require(prepared.wasOk(), prepared.getErrorMessage().toRawUTF8());
    reference->play();
  }

  void Render(studio::StudioAudioEngine* engine) {
    Require(reference != nullptr, "The Studio Duo reference engine is missing");
    if (reference->positionSeconds() > 3) {
      reference->seekSeconds(0);
      engine->seekSeconds(0);
    }
    const auto started = std::chrono::steady_clock::now();
    const auto actual = engine->renderActiveBlockForTesting(256, 2);
    maximumRenderMicros = std::max(maximumRenderMicros,
      std::chrono::duration<double, std::micro>(std::chrono::steady_clock::now() - started).count());
    const auto expected = reference->renderActiveBlockForTesting(256, 2);
    Require(actual.getNumChannels() == 2 && actual.getNumSamples() == 256, "Studio Duo returned invalid playback dimensions");
    float peak = 0;
    for (int channel = 0; channel < 2; ++channel)
      for (int sample = 0; sample < 256; ++sample) {
        const auto value = actual.getSample(channel, sample);
        peak = std::max(peak, std::abs(expected.getSample(channel, sample)));
        Require(std::isfinite(value) && std::abs(value - expected.getSample(channel, sample)) < 1e-5,
                "Offline separation changed Studio Duo's actual live playback");
      }
    if (peak > 1e-5) ++audibleBlocks;
    sampleTime += 256;
  }
};

struct Instance {
  std::unique_ptr<studio::StudioAudioEngine> engine;
  studio::StudioAudioEngine* unit = nullptr;
  studio::Project project;
  juce::String insertId;
  juce::File evidence;
};

HostComponent CreateComponent(const char* path, const char* fixture, const char* evidence) {
  juce::AudioPluginFormatManager formats;
  studio::PluginFormats::addSupportedFormats(formats);
  juce::OwnedArray<juce::PluginDescription> candidates;
  const bool audioUnit = juce::File(juce::String::fromUTF8(path)).hasFileExtension("component");
  for (auto* format : formats.getFormats())
    if (format->getName() == (audioUnit ? "AudioUnit" : "VST3"))
      format->findAllTypesForFile(candidates, audioUnit ? "AudioUnit:Effects/aufx,T2St,T2Sm" : juce::String::fromUTF8(path));
  Require(candidates.size() == 1, "Studio Duo did not discover exactly one explicit native plugin");
  return {*candidates[0], juce::File(juce::String::fromUTF8(fixture)), juce::File(juce::String::fromUTF8(evidence))};
}

SavedState SaveState(Instance& instance) {
  const auto captures = instance.unit->capturePluginStates(5000);
  const auto captured = std::find_if(captures.begin(), captures.end(), [&](const auto& value) {
    return value.insertId == instance.insertId;
  });
  Require(captured != captures.end() && captured->result.wasOk() && !captured->state.isEmpty(),
          "Studio Duo could not capture the actual VST3 project state");
  const auto package = instance.evidence.getChildFile("Track2stem.studioduo");
  if (!package.exists())
    Require(studio::ProjectFile::save(instance.project, package).wasOk(), "Cannot create the actual Studio Duo project package");
  juce::String error;
  const auto stored = studio::PluginStateStore::store(package, captured->state, error);
  Require(stored.has_value(), error.toRawUTF8());
  auto& insert = instance.project.tracks.front().inserts.front();
  insert.stateFile = stored->relativePath;
  insert.stateHash = stored->hash;
  const auto saved = studio::ProjectFile::save(instance.project, package);
  Require(saved.wasOk(), saved.getErrorMessage().toRawUTF8());
  return package;
}

WKWebView* Open(Instance& instance, const HostComponent& component, Audio& audio, const SavedState& saved = {}) {
  instance.evidence = component.evidence;
  juce::MemoryBlock state;
  if (saved.exists()) {
    juce::String error;
    const auto loaded = studio::ProjectFile::load(saved, error);
    Require(loaded.has_value(), error.toRawUTF8());
    instance.project = *loaded;
    const auto& insert = instance.project.tracks.front().inserts.front();
    Require(studio::PluginStateStore::load(saved, {insert.stateFile, insert.stateHash}, state, error),
            error.toRawUTF8());
  } else {
    instance.project = studio::Project::createDefault();
    instance.project.name = "Track2stem synthetic native workflow";
    instance.project.metronomeEnabled = false;
    juce::AudioFormatManager audioFormats;
    audioFormats.registerBasicFormats();
    std::unique_ptr<juce::AudioFormatReader> reader(audioFormats.createReaderFor(component.fixture));
    Require(reader != nullptr, "Studio Duo cannot read the generated playback fixture");
    studio::AudioClip clip;
    clip.name = "Generated playback";
    clip.sourceFile = component.fixture;
    clip.durationSeconds = clip.sourceLengthSeconds = clip.sourceRangeEndSeconds =
      static_cast<double>(reader->lengthInSamples) / reader->sampleRate;
    instance.project.tracks.front().clips.push_back(clip);
    studio::PluginInsert insert;
    insert.pluginIdentifier = component.description.createIdentifierString();
    insert.name = component.description.name;
    insert.manufacturer = component.description.manufacturerName;
    insert.format = component.description.pluginFormatName;
    insert.version = component.description.version;
    insert.architecture = "arm64";
    insert.fileOrIdentifier = component.description.fileOrIdentifier;
    insert.bridgeMode = studio::PluginBridgeMode::trustedInProcess;
    instance.project.tracks.front().inserts.push_back(insert);
  }
  const auto& insert = instance.project.tracks.front().inserts.front();
  instance.insertId = insert.id;
  studio::StudioAudioEngine::PluginRuntimeRequest request;
  request.trackId = instance.project.tracks.front().id;
  request.insertId = insert.id;
  request.name = insert.name;
  request.description = component.description;
  request.state = state;
  request.bridgeMode = studio::PluginBridgeMode::trustedInProcess;
  instance.engine = std::make_unique<studio::StudioAudioEngine>();
  instance.unit = instance.engine.get();
  Require(instance.unit->configureAudioForTesting(48000, 256).wasOk(), "Cannot configure Studio Duo software playback");
  const auto prepared = instance.unit->updateProject(instance.project, {request});
  Require(prepared.wasOk(), prepared.getErrorMessage().toRawUTF8());
  Require(Wait([&] {
    for (const auto& status : instance.unit->pluginRuntimeStatuses())
      if (status.insertId == insert.id && status.state == studio::StudioAudioEngine::PluginRuntimeStatus::State::ready)
        return true;
    return false;
  }, 20), "Studio Duo did not make the actual VST3 ready");
  audio.Configure(instance.project);
  instance.unit->play();
  const auto opened = instance.unit->showPluginEditor(insert.id);
  Require(opened.wasOk(), opened.getErrorMessage().toRawUTF8());
  WKWebView* web = nil;
  Require(Wait([&] {
    for (NSWindow* window in NSApp.windows)
      if ((web = FindWeb(window.contentView))) return true;
    return false;
  }, 15), "Studio Duo did not create the actual VST3 WebView editor");
  WaitForNativeUI(web, [&] { audio.Render(instance.unit); });
  return web;
}
