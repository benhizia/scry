// Execute les fonctions de rendu generees par Scry sans fenetre ni backend :
// NewFrame, dessin de chaque structure, Render. Utilise par tests/test_corpus.py.
//
// Chaque structure est dessinee deux fois : sur le motif de demo, et sur une
// instance construite par defaut quand le registre en propose une. Prendre
// l'adresse de default_instance<T> l'instancie : si un constructeur defini
// hors du header y etait appele, ce programme ne se lierait pas.
#include "introspection.generated.h"

#include <cstdio>
#include <vector>

int main()
{
    ImGui::CreateContext();
    ImGuiIO& io = ImGui::GetIO();
    io.DisplaySize = ImVec2(1600.0f, 900.0f);
    io.Fonts->Build();
    std::size_t instances = 0;
    for (int frame = 0; frame < 2; ++frame) {
        ImGui::NewFrame();
        ImGui::Begin("scry");
        instances = 0;
        for (std::size_t i = 0; i < scry::kStructCount; ++i) {
            const scry::StructInfo& info = scry::kStructs[i];
            std::vector<std::uint8_t> demo(info.size);
            for (std::size_t k = 0; k < demo.size(); ++k)
                demo[k] = static_cast<std::uint8_t>((k * 7 + 3) % 251);
            info.draw(demo.data());
            if (const std::uint8_t* instance = info.default_instance()) {
                info.draw(instance);
                ++instances;
            }
        }
        ImGui::End();
        ImGui::Render();
    }
    std::printf("structures=%zu instances=%zu\n", scry::kStructCount, instances);
    ImGui::DestroyContext();
    return 0;
}
