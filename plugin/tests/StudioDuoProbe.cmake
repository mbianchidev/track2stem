function(track2stem_attach_studio_duo_probe)
  if(NOT TARGET StudioDuoTests)
    message(FATAL_ERROR "The pinned Studio Duo test target is unavailable")
  endif()
  set(PROBE_DIRECTORY "${CMAKE_CURRENT_FUNCTION_LIST_DIR}")
  set_property(SOURCE "${CMAKE_CURRENT_SOURCE_DIR}/tests/ModelTests.cpp"
    APPEND PROPERTY COMPILE_DEFINITIONS "main=StudioDuoOriginalMain")
  target_sources(StudioDuoTests PRIVATE "${PROBE_DIRECTORY}/NativeSmoke.mm")
  set_property(SOURCE "${PROBE_DIRECTORY}/NativeSmoke.mm" APPEND PROPERTY COMPILE_OPTIONS "-fobjc-arc")
  set_property(SOURCE "${PROBE_DIRECTORY}/NativeSmoke.mm"
    APPEND PROPERTY COMPILE_DEFINITIONS TRACK2STEM_STUDIO_DUO_PROBE=1)
  target_include_directories(StudioDuoTests PRIVATE "${PROBE_DIRECTORY}")
  target_link_libraries(StudioDuoTests PRIVATE "-framework WebKit" "-framework AppKit")
endfunction()

cmake_language(DEFER CALL track2stem_attach_studio_duo_probe)
