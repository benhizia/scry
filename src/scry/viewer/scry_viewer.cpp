// =============================================================================
//  Scry - visualiseur C++ natif
//
//  Affiche les structures avec les fonctions de rendu GENEREES par Scry
//  (introspection.generated.h). Si cet executable compile, les static_assert
//  d'ABI du header genere sont passes : les offsets affiches sont ceux du
//  compilateur, dans cette configuration de build.
//
//  Deux sources d'octets :
//    - instance C++ : un objet construit par defaut, initialiseurs de membres
//      compris. Indisponible pour un type abstrait ou non constructible ;
//    - motif de demo : un buffer rempli par (i * 7 + 3) % 251, exactement les
//      octets de scry.runtime.memory.make_demo_buffer. L'IHM Python en mode
//      demo doit afficher les memes valeurs.
//
//  Compile par 'scry viewer' (scry/viewer/build.py), qui fournit les -I vers
//  ImGui, ses backends, le dossier Generated et les headers sources.
//  Fenetre Win32 et DirectX 11 : rien a installer hors du Windows SDK. La
//  partie plateforme suit examples/example_win32_directx11 de Dear ImGui.
// =============================================================================

#include "introspection.generated.h"

#include "imgui.h"
#include "imgui_impl_dx11.h"
#include "imgui_impl_win32.h"

#ifndef NOMINMAX
#define NOMINMAX
#endif
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <d3d11.h>

#include <cstdint>
#include <cstring>
#include <vector>

// Namespace du code genere, [codegen] namespace de scry.ini.
#ifndef SCRY_NS
#define SCRY_NS scry
#endif
namespace gen = SCRY_NS;

// -----------------------------------------------------------------------------
// Etat et donnees
// -----------------------------------------------------------------------------
namespace {

enum class Source { Instance, Demo };

struct ViewerState
{
    std::size_t selected = 0;
    int source = 0;  // Source, en int pour ImGui::RadioButton
};

// Meme motif que make_demo_buffer cote Python, un buffer par structure.
const std::uint8_t* demo_buffer(std::size_t index)
{
    static std::vector<std::vector<std::uint8_t>> buffers(gen::kStructCount);
    std::vector<std::uint8_t>& buffer = buffers[index];
    if (buffer.empty()) {
        buffer.resize(gen::kStructs[index].size);
        for (std::size_t i = 0; i < buffer.size(); ++i)
            buffer[i] = static_cast<std::uint8_t>((i * 7 + 3) % 251);
    }
    return buffer.data();
}

const char* build_label()
{
#if defined(_DEBUG)
    return "runtime debug (/MDd), _ITERATOR_DEBUG_LEVEL=" _CRT_STRINGIZE(_ITERATOR_DEBUG_LEVEL);
#else
    return "runtime release (/MD), _ITERATOR_DEBUG_LEVEL=" _CRT_STRINGIZE(_ITERATOR_DEBUG_LEVEL);
#endif
}

const ImVec4 kPaddingColor(0.95f, 0.60f, 0.25f, 1.0f);

// -----------------------------------------------------------------------------
// Interface : meme organisation que l'IHM Python, liste a gauche et
// tree-table genere a droite.
// -----------------------------------------------------------------------------
void draw_structs(ViewerState& state, float reserve)
{
    ImGui::Text("Structures");
    ImGui::SameLine();
    ImGui::TextDisabled("(%zu)", gen::kStructCount);
    const ImGuiTableFlags flags = ImGuiTableFlags_RowBg | ImGuiTableFlags_ScrollY |
                                  ImGuiTableFlags_SizingStretchProp;
    if (!ImGui::BeginTable("liste", 3, flags, ImVec2(0.0f, -reserve)))
        return;
    ImGui::TableSetupScrollFreeze(0, 1);
    ImGui::TableSetupColumn("Nom", ImGuiTableColumnFlags_WidthStretch, 1.0f);
    ImGui::TableSetupColumn("sizeof", ImGuiTableColumnFlags_WidthFixed, 52.0f);
    ImGui::TableSetupColumn("pad", ImGuiTableColumnFlags_WidthFixed, 36.0f);
    ImGui::TableHeadersRow();
    for (std::size_t i = 0; i < gen::kStructCount; ++i) {
        const gen::StructInfo& info = gen::kStructs[i];
        ImGui::TableNextRow();
        ImGui::TableNextColumn();
        ImGui::PushID(static_cast<int>(i));
        char label[512];
        std::snprintf(label, sizeof(label), "%s%s", info.name, info.polymorphic ? "  (v)" : "");
        if (ImGui::Selectable(label, state.selected == i, ImGuiSelectableFlags_SpanAllColumns))
            state.selected = i;
        if (ImGui::IsItemHovered() && info.default_instance() == nullptr)
            ImGui::SetTooltip("Abstrait ou non constructible par defaut :\n"
                              "seul le motif de demo est disponible.");
        ImGui::PopID();
        ImGui::TableNextColumn();
        ImGui::Text("%zu", info.size);
        ImGui::TableNextColumn();
        if (info.padding)
            ImGui::TextColored(kPaddingColor, "%zu", info.padding);
        else
            ImGui::TextDisabled("0");
    }
    ImGui::EndTable();
}

void draw_members(ViewerState& state, float reserve)
{
    const gen::StructInfo& info = gen::kStructs[state.selected];
    ImGui::Text("%s", info.name);
    ImGui::SameLine();
    ImGui::TextDisabled("sizeof %zu   alignof %zu   padding %zu%s", info.size, info.align,
                        info.padding, info.polymorphic ? "   polymorphe" : "");

    const std::uint8_t* base = state.source == static_cast<int>(Source::Instance)
                                   ? info.default_instance()
                                   : demo_buffer(state.selected);
    if (base == nullptr) {
        ImGui::TextColored(kPaddingColor, "Type abstrait ou non constructible par defaut : "
                                          "passer en motif de demo.");
        return;
    }
    ImGui::BeginChild("membres", ImVec2(0.0f, -reserve));
    info.draw(base);
    ImGui::EndChild();
}

void draw_ui(ViewerState& state)
{
    const ImGuiViewport* viewport = ImGui::GetMainViewport();
    ImGui::SetNextWindowPos(viewport->WorkPos);
    ImGui::SetNextWindowSize(viewport->WorkSize);
    const ImGuiWindowFlags root_flags = ImGuiWindowFlags_NoDecoration | ImGuiWindowFlags_NoMove |
                                        ImGuiWindowFlags_NoSavedSettings |
                                        ImGuiWindowFlags_NoBringToFrontOnFocus;
    ImGui::PushStyleVar(ImGuiStyleVar_WindowRounding, 0.0f);
    ImGui::Begin("Scry viewer", nullptr, root_flags);
    ImGui::PopStyleVar();

    // Barre d'outils
    ImGui::Text("Memoire");
    ImGui::SameLine();
    ImGui::RadioButton("instance C++ (initialiseurs par defaut)", &state.source,
                       static_cast<int>(Source::Instance));
    ImGui::SameLine();
    ImGui::RadioButton("motif de demo", &state.source, static_cast<int>(Source::Demo));
    if (ImGui::IsItemHovered())
        ImGui::SetTooltip("Buffer rempli par (i * 7 + 3) %% 251 : les memes octets que\n"
                          "l'IHM Python en mode motif de demo.");
    ImGui::SameLine();
    ImGui::TextDisabled("   |   ImGui %s   |   %s", IMGUI_VERSION, build_label());
    ImGui::Separator();

    const float reserve = ImGui::GetFrameHeightWithSpacing();
    if (ImGui::BeginTable("layout", 2, ImGuiTableFlags_Resizable | ImGuiTableFlags_BordersInnerV)) {
        ImGui::TableSetupColumn("Structures", ImGuiTableColumnFlags_WidthStretch, 0.25f);
        ImGui::TableSetupColumn("Membres", ImGuiTableColumnFlags_WidthStretch, 0.75f);
        ImGui::TableNextRow();
        ImGui::TableNextColumn();
        draw_structs(state, reserve);
        ImGui::TableNextColumn();
        draw_members(state, reserve);
        ImGui::EndTable();
    }

    ImGui::Separator();
    ImGui::TextDisabled("%zu structure(s)   |   static_assert d'ABI valides a la compilation "
                        "pour cette configuration", gen::kStructCount);
    ImGui::End();
}

}  // namespace

// -----------------------------------------------------------------------------
// Plateforme : Win32 + DirectX 11, d'apres l'exemple officiel de Dear ImGui
// -----------------------------------------------------------------------------
static ID3D11Device* g_pd3dDevice = nullptr;
static ID3D11DeviceContext* g_pd3dDeviceContext = nullptr;
static IDXGISwapChain* g_pSwapChain = nullptr;
static bool g_SwapChainOccluded = false;
static UINT g_ResizeWidth = 0, g_ResizeHeight = 0;
static ID3D11RenderTargetView* g_mainRenderTargetView = nullptr;

static bool CreateDeviceD3D(HWND hWnd);
static void CleanupDeviceD3D();
static void CreateRenderTarget();
static void CleanupRenderTarget();
static LRESULT WINAPI WndProc(HWND hWnd, UINT msg, WPARAM wParam, LPARAM lParam);

// Options : --demo demarre en motif de demo, --struct NOM sur une structure.
static void parse_args(int argc, char** argv, ViewerState& state)
{
    for (int i = 1; i < argc; ++i) {
        if (std::strcmp(argv[i], "--demo") == 0) {
            state.source = static_cast<int>(Source::Demo);
        } else if (std::strcmp(argv[i], "--struct") == 0 && i + 1 < argc) {
            const char* wanted = argv[++i];
            for (std::size_t k = 0; k < gen::kStructCount; ++k)
                if (std::strcmp(gen::kStructs[k].name, wanted) == 0)
                    state.selected = k;
        }
    }
}

int main(int argc, char** argv)
{
    ViewerState state;
    parse_args(argc, argv, state);

    ImGui_ImplWin32_EnableDpiAwareness();
    const float main_scale = ImGui_ImplWin32_GetDpiScaleForMonitor(
        ::MonitorFromPoint(POINT{0, 0}, MONITOR_DEFAULTTOPRIMARY));

    WNDCLASSEXW wc = {sizeof(wc), CS_CLASSDC, WndProc, 0L, 0L, GetModuleHandle(nullptr),
                      nullptr, nullptr, nullptr, nullptr, L"ScryViewer", nullptr};
    ::RegisterClassExW(&wc);
    HWND hwnd = ::CreateWindowW(wc.lpszClassName, L"Scry - visualiseur C++ natif",
                                WS_OVERLAPPEDWINDOW, 100, 100, static_cast<int>(1600 * main_scale),
                                static_cast<int>(900 * main_scale), nullptr, nullptr,
                                wc.hInstance, nullptr);

    if (!CreateDeviceD3D(hwnd)) {
        CleanupDeviceD3D();
        ::UnregisterClassW(wc.lpszClassName, wc.hInstance);
        return 1;
    }
    ::ShowWindow(hwnd, SW_SHOWDEFAULT);
    ::UpdateWindow(hwnd);

    IMGUI_CHECKVERSION();
    ImGui::CreateContext();
    ImGuiIO& io = ImGui::GetIO();
    io.ConfigFlags |= ImGuiConfigFlags_NavEnableKeyboard;
    io.IniFilename = nullptr;  // layout recalcule a chaque frame, rien a sauver

    ImGui::StyleColorsDark();
    ImGuiStyle& style = ImGui::GetStyle();
    style.ScaleAllSizes(main_scale);
    style.FontScaleDpi = main_scale;

    ImGui_ImplWin32_Init(hwnd);
    ImGui_ImplDX11_Init(g_pd3dDevice, g_pd3dDeviceContext);

    const float clear_color[4] = {0.10f, 0.10f, 0.12f, 1.0f};

    bool done = false;
    while (!done) {
        MSG msg;
        while (::PeekMessage(&msg, nullptr, 0U, 0U, PM_REMOVE)) {
            ::TranslateMessage(&msg);
            ::DispatchMessage(&msg);
            if (msg.message == WM_QUIT)
                done = true;
        }
        if (done)
            break;

        if (g_SwapChainOccluded && g_pSwapChain->Present(0, DXGI_PRESENT_TEST) == DXGI_STATUS_OCCLUDED) {
            ::Sleep(10);
            continue;
        }
        g_SwapChainOccluded = false;

        if (g_ResizeWidth != 0 && g_ResizeHeight != 0) {
            CleanupRenderTarget();
            g_pSwapChain->ResizeBuffers(0, g_ResizeWidth, g_ResizeHeight, DXGI_FORMAT_UNKNOWN, 0);
            g_ResizeWidth = g_ResizeHeight = 0;
            CreateRenderTarget();
        }

        ImGui_ImplDX11_NewFrame();
        ImGui_ImplWin32_NewFrame();
        ImGui::NewFrame();

        draw_ui(state);

        ImGui::Render();
        g_pd3dDeviceContext->OMSetRenderTargets(1, &g_mainRenderTargetView, nullptr);
        g_pd3dDeviceContext->ClearRenderTargetView(g_mainRenderTargetView, clear_color);
        ImGui_ImplDX11_RenderDrawData(ImGui::GetDrawData());

        const HRESULT hr = g_pSwapChain->Present(1, 0);
        g_SwapChainOccluded = (hr == DXGI_STATUS_OCCLUDED);
    }

    ImGui_ImplDX11_Shutdown();
    ImGui_ImplWin32_Shutdown();
    ImGui::DestroyContext();

    CleanupDeviceD3D();
    ::DestroyWindow(hwnd);
    ::UnregisterClassW(wc.lpszClassName, wc.hInstance);
    return 0;
}

static bool CreateDeviceD3D(HWND hWnd)
{
    DXGI_SWAP_CHAIN_DESC sd;
    ZeroMemory(&sd, sizeof(sd));
    sd.BufferCount = 2;
    sd.BufferDesc.Format = DXGI_FORMAT_R8G8B8A8_UNORM;
    sd.BufferDesc.RefreshRate.Numerator = 60;
    sd.BufferDesc.RefreshRate.Denominator = 1;
    sd.Flags = DXGI_SWAP_CHAIN_FLAG_ALLOW_MODE_SWITCH;
    sd.BufferUsage = DXGI_USAGE_RENDER_TARGET_OUTPUT;
    sd.OutputWindow = hWnd;
    sd.SampleDesc.Count = 1;
    sd.Windowed = TRUE;
    sd.SwapEffect = DXGI_SWAP_EFFECT_DISCARD;

    const UINT createDeviceFlags = 0;
    D3D_FEATURE_LEVEL featureLevel;
    const D3D_FEATURE_LEVEL featureLevelArray[2] = {D3D_FEATURE_LEVEL_11_0, D3D_FEATURE_LEVEL_10_0};
    HRESULT res = D3D11CreateDeviceAndSwapChain(nullptr, D3D_DRIVER_TYPE_HARDWARE, nullptr,
                                                createDeviceFlags, featureLevelArray, 2,
                                                D3D11_SDK_VERSION, &sd, &g_pSwapChain,
                                                &g_pd3dDevice, &featureLevel, &g_pd3dDeviceContext);
    if (res == DXGI_ERROR_UNSUPPORTED)  // pas de GPU : pilote logiciel WARP
        res = D3D11CreateDeviceAndSwapChain(nullptr, D3D_DRIVER_TYPE_WARP, nullptr,
                                            createDeviceFlags, featureLevelArray, 2,
                                            D3D11_SDK_VERSION, &sd, &g_pSwapChain, &g_pd3dDevice,
                                            &featureLevel, &g_pd3dDeviceContext);
    if (res != S_OK)
        return false;
    CreateRenderTarget();
    return true;
}

static void CleanupDeviceD3D()
{
    CleanupRenderTarget();
    if (g_pSwapChain) { g_pSwapChain->Release(); g_pSwapChain = nullptr; }
    if (g_pd3dDeviceContext) { g_pd3dDeviceContext->Release(); g_pd3dDeviceContext = nullptr; }
    if (g_pd3dDevice) { g_pd3dDevice->Release(); g_pd3dDevice = nullptr; }
}

static void CreateRenderTarget()
{
    ID3D11Texture2D* pBackBuffer = nullptr;
    g_pSwapChain->GetBuffer(0, IID_PPV_ARGS(&pBackBuffer));
    g_pd3dDevice->CreateRenderTargetView(pBackBuffer, nullptr, &g_mainRenderTargetView);
    pBackBuffer->Release();
}

static void CleanupRenderTarget()
{
    if (g_mainRenderTargetView) { g_mainRenderTargetView->Release(); g_mainRenderTargetView = nullptr; }
}

extern IMGUI_IMPL_API LRESULT ImGui_ImplWin32_WndProcHandler(HWND hWnd, UINT msg, WPARAM wParam,
                                                             LPARAM lParam);

static LRESULT WINAPI WndProc(HWND hWnd, UINT msg, WPARAM wParam, LPARAM lParam)
{
    if (ImGui_ImplWin32_WndProcHandler(hWnd, msg, wParam, lParam))
        return true;
    switch (msg) {
    case WM_SIZE:
        if (wParam == SIZE_MINIMIZED)
            return 0;
        g_ResizeWidth = static_cast<UINT>(LOWORD(lParam));
        g_ResizeHeight = static_cast<UINT>(HIWORD(lParam));
        return 0;
    case WM_SYSCOMMAND:
        if ((wParam & 0xfff0) == SC_KEYMENU)  // pas de menu ALT
            return 0;
        break;
    case WM_DESTROY:
        ::PostQuitMessage(0);
        return 0;
    }
    return ::DefWindowProcW(hWnd, msg, wParam, lParam);
}
