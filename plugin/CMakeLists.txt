cmake_minimum_required(VERSION 3.24)
project(Track2stem VERSION 0.1.0 LANGUAGES C CXX OBJC OBJCXX)

if(NOT APPLE)
  message(FATAL_ERROR "The initial plugin target is macOS Apple Silicon.")
endif()
set(CMAKE_OSX_ARCHITECTURES "arm64" CACHE STRING "Supported architecture")
set(CMAKE_OSX_DEPLOYMENT_TARGET "14.0" CACHE STRING "Minimum macOS version")
include(FetchContent)
FetchContent_Declare(iplug2
  GIT_REPOSITORY https://github.com/iPlug2/iPlug2.git
  GIT_TAG b320ce3b08057635e10d812d1b0773867772d8b6
  GIT_SHALLOW TRUE
  SOURCE_SUBDIR _track2stem_dependency_only
)
FetchContent_MakeAvailable(iplug2)
find_package(Git REQUIRED)
set(TRACK2STEM_WEBVIEW_PATCH "${CMAKE_CURRENT_SOURCE_DIR}/patches/webview.patch")
execute_process(COMMAND "${GIT_EXECUTABLE}" apply --reverse --check "${TRACK2STEM_WEBVIEW_PATCH}"
  WORKING_DIRECTORY "${iplug2_SOURCE_DIR}" RESULT_VARIABLE TRACK2STEM_PATCH_APPLIED
  OUTPUT_QUIET ERROR_QUIET)
if(NOT TRACK2STEM_PATCH_APPLIED EQUAL 0)
  execute_process(COMMAND "${GIT_EXECUTABLE}" apply "${TRACK2STEM_WEBVIEW_PATCH}"
    WORKING_DIRECTORY "${iplug2_SOURCE_DIR}" RESULT_VARIABLE TRACK2STEM_PATCH_RESULT)
  if(NOT TRACK2STEM_PATCH_RESULT EQUAL 0)
    message(FATAL_ERROR "Cannot apply the pinned WebView navigation/export fixes.")
  endif()
endif()
FetchContent_Declare(vst3sdk
  GIT_REPOSITORY https://github.com/SteinbergMedia/vst3sdk.git
  GIT_TAG 3cdf9ca5d1f5b1b21e0a86832aa4abe55607bd96
  GIT_SUBMODULES pluginterfaces base public.sdk cmake
  SOURCE_DIR "${iplug2_SOURCE_DIR}/Dependencies/IPlug/VST3_SDK"
  SOURCE_SUBDIR _track2stem_dependency_only
)
FetchContent_MakeAvailable(vst3sdk)
set(IPLUG2_DIR "${iplug2_SOURCE_DIR}")
set(IPLUG_DEPLOY_PLUGINS OFF CACHE BOOL "Never install plugins while building" FORCE)
include("${IPLUG2_DIR}/iPlug2.cmake")
find_package(iPlug2 REQUIRED)

set(TRACK2STEM_WEB_DIR "${CMAKE_CURRENT_BINARY_DIR}/web" CACHE PATH "Vite bundle with a relative base")
iplug_add_plugin(Track2stem
  SOURCES Track2stem.cpp Track2stem.h WorkerClient.mm WorkerClient.h resources/resource.h
  FORMATS VST3 AU
  UI WEBVIEW
)
file(GLOB_RECURSE TRACK2STEM_WEB_ASSETS CONFIGURE_DEPENDS "${TRACK2STEM_WEB_DIR}/*")
foreach(format IN ITEMS vst3 au)
  set_property(TARGET Track2stem-${format} APPEND PROPERTY LINK_DEPENDS "${TRACK2STEM_WEB_ASSETS}")
  add_custom_command(TARGET Track2stem-${format} POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E remove_directory
      "${CMAKE_CURRENT_BINARY_DIR}/out/Track2stem.$<IF:$<STREQUAL:${format},vst3>,vst3,component>/Contents/Resources/web"
    COMMAND ${CMAKE_COMMAND} -E copy_directory "${TRACK2STEM_WEB_DIR}"
      "${CMAKE_CURRENT_BINARY_DIR}/out/Track2stem.$<IF:$<STREQUAL:${format},vst3>,vst3,component>/Contents/Resources/web"
  )
endforeach()

add_library(track2stem-au-registration SHARED EXCLUDE_FROM_ALL tests/RegisterAudioUnit.mm)
target_link_libraries(track2stem-au-registration PRIVATE "-framework Foundation" "-framework AudioToolbox")
set_source_files_properties(tests/RegisterAudioUnit.mm PROPERTIES COMPILE_OPTIONS "-fobjc-arc")

add_executable(track2stem-native-smoke EXCLUDE_FROM_ALL tests/NativeSmoke.mm)
target_link_libraries(track2stem-native-smoke PRIVATE "-framework AppKit" "-framework AudioToolbox"
  "-framework AudioUnit" "-framework WebKit")
set_source_files_properties(tests/NativeSmoke.mm PROPERTIES COMPILE_OPTIONS "-fobjc-arc")
