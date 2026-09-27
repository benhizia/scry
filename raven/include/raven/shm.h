// Memoire partagee nommee, Windows et POSIX. Header seul : le simulateur
// l'inclut via producer.h sans lier de bibliotheque RAVEN.
#pragma once
#include <cstddef>
#include <cstdint>
#include <string>

#ifdef _WIN32
#  ifndef WIN32_LEAN_AND_MEAN
#    define WIN32_LEAN_AND_MEAN
#  endif
#  ifndef NOMINMAX
#    define NOMINMAX
#  endif
#  include <windows.h>
#else
#  include <fcntl.h>
#  include <sys/mman.h>
#  include <sys/stat.h>
#  include <unistd.h>
#endif

namespace raven {

class SharedMemory {
public:
    SharedMemory() = default;
    SharedMemory(const SharedMemory&) = delete;
    SharedMemory& operator=(const SharedMemory&) = delete;
    ~SharedMemory() { close(); }

    // Cree (ou recree) le segment : cote simulateur.
    bool create(const std::string& name, size_t size) { return map(name, size, true); }
    // Ouvre un segment existant : cote RAVEN.
    bool open(const std::string& name, size_t size) { return map(name, size, false); }

    void* data() const { return data_; }
    size_t size() const { return size_; }

    void close() {
        if (!data_) return;
#ifdef _WIN32
        UnmapViewOfFile(data_);
        CloseHandle(handle_);
        handle_ = nullptr;
#else
        munmap(data_, size_);
        if (owner_) shm_unlink(posix_name_.c_str());
#endif
        data_ = nullptr;
        size_ = 0;
    }

private:
    bool map(const std::string& name, size_t size, bool create) {
        close();
#ifdef _WIN32
        const std::string n = "Local\\raven." + name;
        handle_ = create
            ? CreateFileMappingA(INVALID_HANDLE_VALUE, nullptr, PAGE_READWRITE,
                                 DWORD(uint64_t(size) >> 32), DWORD(size & 0xFFFFFFFFu), n.c_str())
            : OpenFileMappingA(FILE_MAP_ALL_ACCESS, FALSE, n.c_str());
        if (!handle_) return false;
        data_ = MapViewOfFile(handle_, FILE_MAP_ALL_ACCESS, 0, 0, size);
        if (!data_) { CloseHandle(handle_); handle_ = nullptr; return false; }
#else
        posix_name_ = "/raven." + name;
        if (create) shm_unlink(posix_name_.c_str());
        int fd = shm_open(posix_name_.c_str(), create ? (O_CREAT | O_RDWR) : O_RDWR, 0600);
        if (fd < 0) return false;
        if (create && ftruncate(fd, off_t(size)) != 0) { ::close(fd); return false; }
        struct stat st;
        if (!create && (fstat(fd, &st) != 0 || size_t(st.st_size) < size)) { ::close(fd); return false; }
        void* p = mmap(nullptr, size, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
        ::close(fd);
        if (p == MAP_FAILED) return false;
        data_ = p;
        owner_ = create;
#endif
        size_ = size;
        return true;
    }

    void* data_ = nullptr;
    size_t size_ = 0;
#ifdef _WIN32
    HANDLE handle_ = nullptr;
#else
    std::string posix_name_;
    bool owner_ = false;
#endif
};

} // namespace raven
