#pragma once
#include <string>

/// Class with nested types and complex relationships
class ComplexSystem {
public:
    /// Nested enumeration
    enum class Status {
        INACTIVE = 0,
        ACTIVE = 1,
        ERROR = 2
    };
    
    /// Nested structure
    struct Configuration {
        // System parameters
        std::string system_name;
        int max_connections;
        double timeout_seconds;
        Status default_status;
    };
    
    /// Nested class
    class EventHandler {
    private:
        // Handler state
        ComplexSystem* parent_system_;
        bool is_enabled_;
        
    public:
        EventHandler(ComplexSystem* parent);
        void handle_event(int event_id);
        bool is_active() const;
    };

private:
    // System state
    Configuration config_;
    EventHandler* handler_;
    Status current_status_;
    
    // Array of subsystem pointers
    ComplexSystem* subsystems_[8];
    int subsystem_count_;

public:
    ComplexSystem(const Configuration& config);
    virtual ~ComplexSystem();
    
    // Status management
    Status get_status() const;
    void set_status(Status new_status);
    
    // Subsystem management
    void add_subsystem(ComplexSystem* subsystem);
    ComplexSystem* get_subsystem(int index) const;
};

/// Multiple inheritance example
class Drawable {
protected:
    int render_priority_;
    
public:
    virtual void draw() = 0;
    int get_priority() const;
};

class Updateable {
protected:
    double last_update_time_;
    
public:
    virtual void update(double delta_time) = 0;
    double get_last_update() const;
};

/// Class with multiple inheritance
class GameObject : public Drawable, public Updateable {
private:
    // Game object properties
    std::string object_name_;
    float position_x_;
    float position_y_;
    bool is_visible_;

public:
    GameObject(const std::string& name, float x, float y);
    
    // Implement pure virtuals
    void draw() override;
    void update(double delta_time) override;
    
    // GameObject-specific methods
    void set_position(float x, float y);
    bool is_at_position(float x, float y) const;
};