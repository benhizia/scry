#pragma once

/// Test struct for inline comments
struct InlineCommentTest {
    int value; // This comment should attach to value
    double price; /* This comment should attach to price */
    bool flag; /* Multi-line
                  comment for flag */
    char type; ///< Doxygen style for type
    float ratio; //!< Another Doxygen style
    long counter; // Counter variable
                  // continues on next line
};