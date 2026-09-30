#include "raven/rvn.h"

#include <cstring>

#ifdef _WIN32
#  define rv_fseek _fseeki64
#  define rv_ftell _ftelli64
#else
#  define rv_fseek fseeko
#  define rv_ftell ftello
#endif

namespace raven {

static const char kMagic[] = "RAVEN-RVN 2\n";
static const char kMagicV1[] = "RAVEN-RVN 1\n";
static const uint32_t kHead = 24;

bool RvnWriter::open(const std::string& path, const Descriptor& d,
                     const std::vector<FieldRef>& sel, const std::string& trigger,
                     std::string& error) {
    close();
    if (sel.empty()) { error = "aucun champ selectionne"; return false; }
    f_ = std::fopen(path.c_str(), "wb");
    if (!f_) { error = "impossible de creer " + path; return false; }
    std::setvbuf(f_, nullptr, _IOFBF, 1 << 20);
    path_ = path;
    ranges_.clear();
    record_size_ = kHead;
    std::string head = kMagic;
    head += d.text();
    for (const FieldRef& r : sel) {
        const FieldDesc* f = d.field(r);
        ranges_.push_back(Range{d.frame_offset(r), f->bytes()});
        record_size_ += f->bytes();
        head += "select " + std::to_string(r.channel) + " " + std::to_string(r.field) + "\n";
    }
    head += "trigger " + (trigger.empty() ? std::string("-") : trigger) + "\n";
    head += "record_size " + std::to_string(record_size_) + "\ndata\n";
    std::fwrite(head.data(), 1, head.size(), f_);
    buf_.resize(record_size_);
    records_ = 0;
    bytes_ = head.size();
    return true;
}

bool RvnWriter::write(uint64_t frame_no, uint64_t t_ns, const unsigned char* frame, int channel) {
    if (!f_) return false;
    unsigned char* p = buf_.data();
    std::memcpy(p, &frame_no, 8);
    std::memcpy(p + 8, &t_ns, 8);
    const int32_t ch = channel;
    const uint32_t reserved = 0;
    std::memcpy(p + 16, &ch, 4);
    std::memcpy(p + 20, &reserved, 4);
    p += kHead;
    for (const Range& r : ranges_) {
        std::memcpy(p, frame + r.offset, r.size);
        p += r.size;
    }
    if (std::fwrite(buf_.data(), 1, record_size_, f_) != record_size_) return false;
    ++records_;
    bytes_ += record_size_;
    return true;
}

void RvnWriter::close() {
    if (f_) std::fclose(f_);
    f_ = nullptr;
}

// Ligne de texte depuis le fichier, sans le '\n'.
static bool read_line(std::FILE* f, std::string& out) {
    out.clear();
    int c;
    while ((c = std::fgetc(f)) != EOF && c != '\n') out.push_back(char(c));
    return c == '\n';
}

bool RvnReader::open(const std::string& path, std::string& error) {
    f_ = std::fopen(path.c_str(), "rb");
    if (!f_) { error = "impossible d'ouvrir " + path; return false; }
    std::string line, desc;
    if (!read_line(f_, line)) { error = "pas un fichier .rvn"; return false; }
    if (line + "\n" == kMagic) { version_ = 2; head_ = kHead; }
    else if (line + "\n" == kMagicV1) { version_ = 1; head_ = 16; }
    else { error = "pas un fichier .rvn"; return false; }
    while (read_line(f_, line)) {
        desc += line + "\n";
        if (line == "end") break;
    }
    if (!desc_.parse(desc, error)) return false;
    while (read_line(f_, line) && line != "data") {
        if (line.compare(0, 7, "select ") == 0) {
            FieldRef r;
            if (std::sscanf(line.c_str() + 7, "%d %d", &r.channel, &r.field) != 2 || !desc_.field(r)) {
                error = "selection invalide : " + line;
                return false;
            }
            sel_.push_back(r);
        } else if (line.compare(0, 8, "trigger ") == 0) {
            trigger_ = line.substr(8);
        } else if (line.compare(0, 12, "record_size ") == 0) {
            record_size_ = uint32_t(std::strtoul(line.c_str() + 12, nullptr, 10));
        }
    }
    if (line != "data") { error = "en-tete tronque"; return false; }
    uint32_t pos = head_;
    for (const FieldRef& r : sel_) {
        field_pos_.push_back(pos);
        pos += desc_.field(r)->bytes();
    }
    if (pos != record_size_) { error = "taille d'enregistrement incoherente"; return false; }
    data_start_ = rv_ftell(f_);
    rv_fseek(f_, 0, SEEK_END);
    count_ = uint64_t(rv_ftell(f_) - data_start_) / record_size_;
    buf_.resize(record_size_);
    return true;
}

bool RvnReader::read(uint64_t n, uint64_t& frame_no, uint64_t& t_ns,
                     std::vector<const unsigned char*>& fields) {
    if (n >= count_) return false;
    rv_fseek(f_, data_start_ + (long long)(n * record_size_), SEEK_SET);
    if (std::fread(buf_.data(), 1, record_size_, f_) != record_size_) return false;
    std::memcpy(&frame_no, buf_.data(), 8);
    std::memcpy(&t_ns, buf_.data() + 8, 8);
    int32_t ch = -1;
    if (head_ >= 24) std::memcpy(&ch, buf_.data() + 16, 4);
    last_channel_ = ch;
    fields.clear();
    for (uint32_t p : field_pos_) fields.push_back(buf_.data() + p);
    return true;
}

} // namespace raven
