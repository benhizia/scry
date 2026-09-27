// Backend GLFW + OpenGL 3 (Linux et autres).
#include <GLFW/glfw3.h>

#include <cstdio>
#include <string>
#include <vector>

#include "backends/imgui_impl_glfw.h"
#include "backends/imgui_impl_opengl3.h"
#include "imgui.h"
#include "options.h"
#include "ui.h"

using namespace raven;


static void save_ppm(const std::string& path, int w, int h) {
    std::vector<unsigned char> px(size_t(w) * h * 3);
    glReadPixels(0, 0, w, h, GL_RGB, GL_UNSIGNED_BYTE, px.data());
    FILE* f = std::fopen(path.c_str(), "wb");
    if (!f) return;
    std::fprintf(f, "P6\n%d %d\n255\n", w, h);
    for (int y = h - 1; y >= 0; --y) std::fwrite(&px[size_t(y) * w * 3], 1, size_t(w) * 3, f);
    std::fclose(f);
}

int run_window(Client& client, UiState& ui, const Options& o) {
    if (!glfwInit()) { std::fprintf(stderr, "GLFW indisponible\n"); return 1; }
    glfwWindowHint(GLFW_CONTEXT_VERSION_MAJOR, 3);
    glfwWindowHint(GLFW_CONTEXT_VERSION_MINOR, 0);
    GLFWwindow* win = glfwCreateWindow(1400, 900, "RAVEN", nullptr, nullptr);
    if (!win) { std::fprintf(stderr, "fenetre impossible\n"); glfwTerminate(); return 1; }
    glfwMakeContextCurrent(win);
    glfwSwapInterval(1);
    ImGui_ImplGlfw_InitForOpenGL(win, true);
    ImGui_ImplOpenGL3_Init("#version 130");
    for (int image = 1; !glfwWindowShouldClose(win); ++image) {
        glfwPollEvents();
        client.tick();
        ImGui_ImplOpenGL3_NewFrame();
        ImGui_ImplGlfw_NewFrame();
        ImGui::NewFrame();
        draw(client, ui);
        ImGui::Render();
        int w, h;
        glfwGetFramebufferSize(win, &w, &h);
        glViewport(0, 0, w, h);
        glClearColor(0.1f, 0.1f, 0.12f, 1);
        glClear(GL_COLOR_BUFFER_BIT);
        ImGui_ImplOpenGL3_RenderDrawData(ImGui::GetDrawData());
        if (!o.screenshot.empty() && image == o.frames) {
            save_ppm(o.screenshot, w, h);
            break;
        }
        glfwSwapBuffers(win);
    }
    ImGui_ImplOpenGL3_Shutdown();
    ImGui_ImplGlfw_Shutdown();
    glfwDestroyWindow(win);
    glfwTerminate();
    return 0;
}
