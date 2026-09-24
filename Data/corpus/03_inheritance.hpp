#pragma once

/// Base class with virtual functions
class Shape {
protected:
    // Position coordinates
    double x_;
    double y_;
    
    // Shape color
    int color_;

public:
    // Constructor
    Shape(double x, double y, int color);
    
    // Virtual destructor
    virtual ~Shape();
    
    // Pure virtual function
    virtual double area() const = 0;
    
    // Virtual function with default implementation
    virtual void draw() const;
    
    // Non-virtual functions
    double get_x() const;
    double get_y() const;
};

/// Derived class - Rectangle
class Rectangle : public Shape {
private:
    // Dimensions
    double width_;
    double height_;

public:
    Rectangle(double x, double y, double width, double height, int color);
    
    // Override virtual functions
    double area() const override;
    void draw() const override;
    
    // Rectangle-specific methods
    double get_width() const;
    double get_height() const;
};