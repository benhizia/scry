# raven-view : IHM ImGui. Backend Win32 + DirectX 11 sous Windows, GLFW +
# OpenGL 3 ailleurs.
set(IMGUI ${RAVEN_IMGUI_DIR})
if(NOT EXISTS "${IMGUI}/imgui.cpp")
  message(WARNING "ImGui introuvable dans ${IMGUI} : raven-view ignore (voir third_party/README.md)")
  return()
endif()

add_library(raven_imgui STATIC
  ${IMGUI}/imgui.cpp ${IMGUI}/imgui_draw.cpp ${IMGUI}/imgui_tables.cpp ${IMGUI}/imgui_widgets.cpp)
target_include_directories(raven_imgui PUBLIC ${IMGUI})

set(VIEW_SOURCES main.cpp client.cpp ui.cpp)
if(WIN32)
  add_executable(raven-view WIN32 ${VIEW_SOURCES} backend_win32.cpp
    ${IMGUI}/backends/imgui_impl_win32.cpp ${IMGUI}/backends/imgui_impl_dx11.cpp)
  target_link_libraries(raven-view PRIVATE d3d11 d3dcompiler dxgi dwmapi)
  if(MSVC)
    # Application fenetree avec main() standard.
    set_target_properties(raven-view PROPERTIES LINK_FLAGS "/ENTRY:mainCRTStartup")
  else()
    target_link_options(raven-view PRIVATE -mconsole)
  endif()
else()
  find_package(glfw3 REQUIRED)
  find_package(OpenGL REQUIRED)
  add_executable(raven-view ${VIEW_SOURCES} backend_glfw.cpp
    ${IMGUI}/backends/imgui_impl_glfw.cpp ${IMGUI}/backends/imgui_impl_opengl3.cpp)
  target_link_libraries(raven-view PRIVATE glfw OpenGL::GL)
endif()
target_link_libraries(raven-view PRIVATE raven_core raven_imgui)
