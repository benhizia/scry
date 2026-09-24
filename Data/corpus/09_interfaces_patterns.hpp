#pragma once
#include <vector>
#include <functional>
#include <mutex>
#include <string>

/// Pure abstract interface
class IObserver {
public:
    // Pure virtual destructor
    virtual ~IObserver() = default;
    
    // Interface methods
    virtual void on_notify(int event_type, void* event_data) = 0;
    virtual bool is_interested_in(int event_type) const = 0;
    virtual int get_priority() const = 0;
};

/// Observable subject interface
class ISubject {
public:
    virtual ~ISubject() = default;
    
    virtual void attach_observer(IObserver* observer) = 0;
    virtual void detach_observer(IObserver* observer) = 0;
    virtual void notify_observers(int event_type, void* event_data) = 0;
};

/// Strategy pattern interface
class ISortStrategy {
public:
    virtual ~ISortStrategy() = default;
    virtual void sort(std::vector<int>& data) = 0;
    virtual const char* get_name() const = 0;
    virtual int get_complexity() const = 0;
};

/// Concrete observer implementation
class EventLogger : public IObserver {
private:
    // Logger configuration
    std::string log_file_path_;
    bool is_enabled_;
    int priority_level_;
    
    // Event filtering
    std::vector<int> interested_events_;
    
    // Statistics
    mutable int events_logged_;
    mutable int events_filtered_;

public:
    EventLogger(const std::string& log_path, int priority = 0);
    virtual ~EventLogger();
    
    // IObserver implementation
    void on_notify(int event_type, void* event_data) override;
    bool is_interested_in(int event_type) const override;
    int get_priority() const override;
    
    // EventLogger specific
    void add_event_filter(int event_type);
    void remove_event_filter(int event_type);
    void enable_logging(bool enabled);
    
    // Statistics
    int get_events_logged() const;
    int get_events_filtered() const;
};

/// Subject implementation with observer pattern
class EventDispatcher : public ISubject {
private:
    // Observer management
    std::vector<IObserver*> observers_;
    
    // Event queue
    struct QueuedEvent {
        int event_type;
        void* event_data;
        double timestamp;
    };
    std::vector<QueuedEvent> event_queue_;
    
    // Dispatcher state
    bool is_processing_;
    int max_queue_size_;

public:
    EventDispatcher(int max_queue_size = 100);
    virtual ~EventDispatcher();
    
    // ISubject implementation
    void attach_observer(IObserver* observer) override;
    void detach_observer(IObserver* observer) override;
    void notify_observers(int event_type, void* event_data) override;
    
    // Event queue management
    void queue_event(int event_type, void* event_data);
    void process_queued_events();
    void clear_queue();
    
    // Statistics
    size_t get_observer_count() const;
    size_t get_queue_size() const;
};

/// Factory pattern example
class ShapeFactory {
private:
    // Factory registry
    using CreateFunction = std::function<void*()>;
    static std::vector<std::pair<std::string, CreateFunction>> registry_;
    
    // Factory statistics
    static int shapes_created_;
    static int factory_instances_;

public:
    ShapeFactory();
    ~ShapeFactory();
    
    // Factory methods
    void* create_shape(const std::string& shape_type);
    bool register_shape_type(const std::string& name, CreateFunction creator);
    std::vector<std::string> get_registered_types() const;
    
    // Template factory method
    template<typename T>
    T* create_typed_shape(const std::string& shape_type);
    
    // Statistics
    static int get_shapes_created();
    static int get_factory_instances();
};

/// Singleton pattern with thread safety
class ConfigManager {
private:
    // Singleton instance
    static ConfigManager* instance_;
    static std::mutex instance_mutex_;
    
    // Configuration data
    std::vector<std::pair<std::string, std::string>> config_pairs_;
    std::string config_file_path_;
    bool is_loaded_;
    mutable std::mutex data_mutex_;

private:
    // Private constructor/destructor
    ConfigManager();
    ~ConfigManager();
    
    // Non-copyable, non-movable
    ConfigManager(const ConfigManager&) = delete;
    ConfigManager& operator=(const ConfigManager&) = delete;

public:
    // Singleton access
    static ConfigManager* get_instance();
    static void destroy_instance();
    
    // Configuration management
    bool load_config(const std::string& file_path);
    bool save_config(const std::string& file_path = "");
    
    void set_value(const std::string& key, const std::string& value);
    std::string get_value(const std::string& key, const std::string& default_val = "") const;
    bool has_key(const std::string& key) const;
    
    // Statistics
    size_t get_config_count() const;
    bool is_config_loaded() const;
};