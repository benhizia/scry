#include <iostream>
struct student
{/*
    struct Metier{
        enum class type_metier
        {
            PHYSIQUE,
            MATH,
            LV1,
            LV2
        };
        type_metier metier;
    };*/
    char name[50];
    int roll;
    float marks;
    //Metier m;
};


struct EmployeeRecord {
    // Personal Information
    class personalInfo{
        personalInfo(){std::cout<<"hello";};
        ~personalInfo(){std::cout<<"bye";};
        virtual void print() = 0;
        virtual void set() = 0;
    public:
        char firstName[50];
        char middleName[50];
        char lastName[50];
        char preferredName[50];
        char gender;
    };
    struct student s5[5];
    int employeeId;
    char firstName[50];
    char lastName[50];
    char middleName[50];
    char preferredName[50];
    char gender;
    char dateOfBirth[11];
    char socialSecurityNumber[12];
    char maritalStatus[20];
    int numberOfDependents;
    
    // Contact Information
    char streetAddress[100];
    char city[50];
    char state[50];
    char country[50];
    char postalCode[20];
    char homePhone[20];
    char mobilePhone[20];
    char workPhone[20];
    char personalEmail[100];
    char workEmail[100];
    char emergencyContactName[100];
    char emergencyContactPhone[20];
    char emergencyContactRelation[50];
    
    // Employment Details
    char dateOfHire[11];
    char department[50];
    char jobTitle[100];
    char employmentStatus[20]; // Full-time, Part-time, Contract, etc.
    double currentSalary;
    char payFrequency[20]; // Weekly, Bi-weekly, Monthly
    int yearsOfService;
    char managerName[100];
    int teamSize;
    char officeLocation[100];
    char workSchedule[100];
    bool isRemoteWorker;
    
    // Skills and Qualifications
    char primarySkill1[50];
    char primarySkill2[50];
    char primarySkill3[50];
    char secondarySkill1[50];
    char secondarySkill2[50];
    char secondarySkill3[50];
    char educationLevel[50];
    char degreeMajor[100];
    char degreeInstitution[100];
    int graduationYear;
    char certification1[100];
    char certification2[100];
    char certification3[100];
    char languageSpoken1[50];
    char languageSpoken2[50];
    char languageSpoken3[50];
    
    // Performance and Reviews
    float lastPerformanceScore;
    char lastReviewDate[11];
    char nextReviewDate[11];
    int goalsAchieved;
    int goalsInProgress;
    char strengthArea1[100];
    char strengthArea2[100];
    char improvementArea1[100];
    char improvementArea2[100];
    
    // Benefits and Compensation
    bool healthInsuranceEnrolled;
    char healthInsurancePlan[50];
    bool dentalInsuranceEnrolled;
    bool visionInsuranceEnrolled;
    bool lifeInsuranceEnrolled;
    double lifeInsuranceAmount;
    bool disability401kEnrolled;
    float disability401kContributionPercentage;
    int paidTimeOffDays;
    int sickDays;
    int vacationDays;
    bool stockOptionEligible;
    int stockOptionsGranted;
    
    // Projects and Assignments
    char currentProject1[100];
    char currentProject2[100];
    char currentProject3[100];
    char pastProject1[100];
    char pastProject2[100];
    char pastProject3[100];
    float projectUtilizationRate;
    int completedMilestones;
    int pendingMilestones;
    
    // Training and Development
    char lastTrainingAttended[100];
    char lastTrainingDate[11];
    char upcomingTraining1[100];
    char upcomingTraining2[100];
    int trainingHoursCompleted;
    int mandatoryTrainingsCompleted;
    int optionalTrainingsCompleted;
    
    // Equipment and Assets
    char assignedLaptopModel[50];
    char assignedLaptopSerialNumber[50];
    char assignedPhoneModel[50];
    char assignedPhoneNumber[20];
    bool hasCompanyCard;
    char companyCardNumber[20];
    double monthlyExpenseLimit;
    
    // Compliance and Legal
    bool backgroundCheckCompleted;
    char lastBackgroundCheckDate[11];
    bool nDAigned;
    char nDAignDate[11];
    bool codeOfConductAcknowledged;
    char lastSecurityTrainingDate[11];
    bool hasAccessToSensitiveData;
    
    // Payroll Information
    char bankName[50];
    char bankAccountNumber[50];
    char bankRoutingNumber[20];
    char taxWithholdingStatus[20];
    int numberOfExemptions;
    bool directDepositEnrolled;
    
    // Time and Attendance
    float averageWeeklyHours;
    float overtimeHoursLastMonth;
    int lateArrivalsLastMonth;
    int absencesLastMonth;
    char typicalShiftStart[10];
    char typicalShiftEnd[10];
    bool eligibleForOvertime;
    
    // Career Development
    char careerPath[100];
    char nextPotentialRole[100];
    int readinessForPromotion; // 1-10 scale
    char mentorName[100];
    char menteeName[100];
    
    // Miscellaneous
    char dietaryRestrictions[100];
    char tShirtSize[10];
    bool parkingPassIssued;
    char buildingAccessCode[20];
    bool isFirstAidCertified;
    bool isFireMarshall;
    char favoriteOfficeSnack[50];
    int coffeeConsumptionPerDay;
    
    // Union Information (if applicable)
    bool isUnionMember;
    char unionName[100];
    char unionMembershipNumber[50];
    
    // International Assignment (if applicable)
    bool isInternationalAssignee;
    char hostCountry[50];
    char assignmentStartDate[11];
    char assignmentEndDate[11];
    bool hasWorkVisa;
    char visaExpirationDate[11];
    
    // Termination Information (if applicable)
    bool isTerminated;
    char terminationDate[11];
    char terminationReason[200];
    bool eligibleForRehire;
};