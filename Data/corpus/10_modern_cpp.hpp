#pragma once
#include <memory>
#include <vector>
#include <unordered_map>
#include <functional>
#include <optional>
#include <variant>
#include <atomic>
#include <mutex>
#include <string>

/// Modern C++ class with auto, lambdas, and smart pointers
class ModernContainer {
private:
    // Smart pointer management
    std::unique_ptr<std::vector<int>> data_;
    std::shared_ptr<std::string> name_;
    
    // STL containers
    std::unordered_map<std::string, std::variant<int, double, std::string>> properties_;
    std::vector<std::function<void(int)>> callbacks_;
    
    // Optional values
    std::optional<double> cached_average_;
    std::optional<std::pair<int, int>> min_max_cache_;
    
    // Modern C++ data members
    mutable std::mutex access_mutex_;
    std::atomic<bool> is_processing_;
    std::atomic<size_t> access_count_;

public:
    // Constructor with initializer list and delegating
    ModernContainer(const std::string& name = "DefaultContainer");
    ModernContainer(std::initializer_list<int> values, const std::string& name = "InitList");
    
    // Rule of 5 with modern semantics
    ~ModernContainer() = default;
    ModernContainer(const ModernContainer& other);
    ModernContainer(ModernContainer&& other) noexcept;
    ModernContainer& operator=(const ModernContainer& other);
    ModernContainer& operator=(ModernContainer&& other) noexcept;
    
    // Template member functions with perfect forwarding
    template<typename T>
    void add_value(T&& value);
    
    template<typename Predicate>
    std::vector<int> filter(Predicate pred) const;
    
    // Lambda and function object support
    void for_each(std::function<void(int)> func) const;
    void add_callback(std::function<void(int)> callback);
    void trigger_callbacks(int value);
    
    // Property management with variant
    template<typename T>
    void set_property(const std::string& key, T&& value);
    
    template<typename T>
    std::optional<T> get_property(const std::string& key) const;
    
    // Constexpr and noexcept methods
    constexpr size_t max_capacity() const noexcept { return 1000000; }
    bool empty() const noexcept;
    size_t size() const noexcept;
    
    // Range-based iteration support
    auto begin() const noexcept -> decltype(data_->begin());
    auto end() const noexcept -> decltype(data_->end());
    
    // Optional value caching
    std::optional<double> get_average() const;
    void invalidate_cache() noexcept;
    
    // Atomic operations
    size_t get_access_count() const noexcept;
    bool is_busy() const noexcept;
};

/// SFINAE and type traits example
template<typename T>
class TypeTraitsExample {
private:
    // Storage for different types
    typename std::aligned_storage<sizeof(T), alignof(T)>::type storage_;
    bool has_value_;
    
    // Type-dependent members
    static constexpr bool is_trivial_ = std::is_trivially_copyable_v<T>;
    static constexpr size_t type_size_ = sizeof(T);
    static constexpr size_t type_align_ = alignof(T);

public:
    // SFINAE constructors
    template<typename U = T>
    TypeTraitsExample(typename std::enable_if_t<std::is_default_constructible_v<U>>* = nullptr);
    
    template<typename U>
    TypeTraitsExample(U&& value, typename std::enable_if_t<std::is_convertible_v<U, T>>* = nullptr);
    
    // Destructor with conditional noexcept
    ~TypeTraitsExample() noexcept(std::is_nothrow_destructible_v<T>);
    
    // Type-dependent methods
    template<typename U = T>
    typename std::enable_if_t<std::is_copy_assignable_v<U>, TypeTraitsExample&>
    operator=(const TypeTraitsExample& other);
    
    template<typename U = T>
    typename std::enable_if_t<std::is_move_assignable_v<U>, TypeTraitsExample&>
    operator=(TypeTraitsExample&& other) noexcept(std::is_nothrow_move_assignable_v<U>);
    
    // Conditional compilation based on type traits
    template<typename U = T>
    auto get_value() const noexcept -> typename std::enable_if_t<is_trivial_, const U&>;
    
    template<typename U = T>
    auto get_value() const -> typename std::enable_if_t<!std::is_trivially_copyable_v<U>, U>;
    
    // Static assertions and compile-time checks
    static_assert(sizeof(T) > 0, "Type must have non-zero size");
    static_assert(!std::is_void_v<T>, "Type cannot be void");
    
    // Constexpr methods
    constexpr bool is_trivial() const noexcept { return is_trivial_; }
    constexpr size_t type_size() const noexcept { return type_size_; }
    constexpr size_t type_alignment() const noexcept { return type_align_; }
};

/// Variadic template and perfect forwarding
template<typename... Args>
class VariadicExample {
private:
    // Tuple to store different types
    std::tuple<Args...> data_;
    
    // Parameter pack size
    static constexpr size_t arg_count_ = sizeof...(Args);
    
    // Index sequence for template expansion
    template<size_t... Is>
    void process_impl(std::index_sequence<Is...>);

public:
    // Perfect forwarding constructor
    template<typename... UArgs>
    VariadicExample(UArgs&&... args) : data_(std::forward<UArgs>(args)...) {}
    
    // Variadic member function
    template<typename Func>
    void apply_to_all(Func&& func);
    
    // Parameter pack expansion
    template<size_t I>
    auto get() const -> const typename std::tuple_element_t<I, std::tuple<Args...>>&;
    
    template<size_t I>
    auto get() -> typename std::tuple_element_t<I, std::tuple<Args...>>&;
    
    // Constexpr utilities
    constexpr size_t size() const noexcept { return arg_count_; }
    
    // Recursive template processing
    template<size_t I = 0>
    void print_types() const;
    
    // SFINAE method availability
    template<typename T>
    auto has_member_func(T&& obj) -> decltype(obj.member_func(), bool{});
    
    template<typename>
    bool has_member_func(...) { return false; }
};

/// Concepts simulation with SFINAE (pre-C++20)
template<typename T>
struct is_container {
    template<typename U>
    static auto test(int) -> decltype(
        std::declval<U>().begin(),
        std::declval<U>().end(),
        std::declval<U>().size(),
        std::true_type{}
    );
    
    template<typename>
    static std::false_type test(...);
    
    static constexpr bool value = decltype(test<T>(0))::value;
};

/// Class using concept-like constraints
template<typename Container>
class ContainerAdapter {
    static_assert(is_container<Container>::value, "Template parameter must be a container");
    
private:
    Container container_;
    std::function<void(typename Container::value_type)> processor_;

public:
    explicit ContainerAdapter(Container&& cont) : container_(std::move(cont)) {}
    
    template<typename Func>
    void set_processor(Func&& func) {
        processor_ = std::forward<Func>(func);
    }
    
    void process_all() {
        if (processor_) {
            for (auto&& item : container_) {
                processor_(item);
            }
        }
    }
    
    auto size() const noexcept -> decltype(container_.size()) {
        return container_.size();
    }
};