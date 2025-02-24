# Road Map

The **d-bee Road Map** is built based on a **wish list** collected from our **Slack community**, where users submit feature requests. Each request is **evaluated, approved (if possible), and prioritized** before being added to the road map.

---

## Following Releases and New Features

### **Create Incremental Package Based on Git History** - *Version 0.9.1*
- Enables comparison between the **current branch state** and its **initial state**.
- Supports comparison of **two different branches** (e.g., `release` vs `master`) to create an **incremental package** for production deployment.
- The **fundamental base** of this feature will be delivered in this version, with enhancements like **auto-deployment order derivation** and **data transfer logic** coming soon.

### **Support for BTEQ Directives in Packages** - *Version 1.0.0*
- **BTEQ**, a scripting language for **Teradata**, is widely used in **ELT jobs** and **deployment packages**.
- This feature will integrate **best practices from senior DBAs**, ensuring stable and controlled deployments.
- **d-bee will enable combining modern Python workflows with the structured stability of BTEQ scripts.**

---

## Approved Longer Road Map

### **Enhancements to Incremental Package Creation**
#### **Auto-Deployment Order**
- Enables automatic determination of the **deployment order** within an incremental package.
- Deployment order is defined based on **package hierarchy** and **alphabetical sorting**.

#### **Data Transfer Creation**
- Generates **data transfer logic** when modifying tables, ensuring:
  - Migration of data from **old to new table versions**.
  - Handling of **NOT NULL column additions** and edge cases.
  - Users are notified to **review and approve decisions** in complex scenarios.

---

### **Compare Feature**
#### **Environment vs. Environment**
- Automated comparison of two database environments.
- Generates an **incremental package** to align them.
- Provides a **detailed report** visualizing gaps.

#### **Environment vs. Git**
- Compares a **database environment** against a **Git branch**.
- Identifies discrepancies and **suggests changes**.

#### **Branch vs. Branch**
- Enables **full comparison** of two **Git branches**.
- Highlights missing objects and differences.

---

### **Enhancements to Package Deployment**
#### **Define Conflict Strategy per Level**
- Users will be able to **define conflict strategies** at multiple levels:
  - **Entire deployment process**
  - **Step level**
  - **Database level**
  - **File level**

---

### **dbt Support**
**dbt (Data Build Tool)** is a widely used framework for **data transformations**. Many teams need a way to **combine database structure modifications with dbt models**.

#### **Planned dbt Features:**
- **Validation of all sources** (ensure they exist).
- **Validate dbt models against DDLs**, ensuring alignment between **dbt logic** and **Teradata structures**.
- **Auto-generate a dbt model** to populate a target table from a source table.
- **Automate dbt test definitions** using PDM (e.g., uniqueness checks based on PKs, referential integrity validation).

---

### **Database Maintenance**
#### **Backup Objects Cleanup**
- Many environments create **backup objects**, leading to clutter.
- This feature will automate **scheduled cleanups**.

---

### **Diagnostics**
#### **Suggest Statistics**
- Analyzes **data-processing objects** (views, stored procedures, macros) to suggest **optimal statistics**.

---

### **VS Code Support** *(Long-Term Plan)*
- **d-bee Integration** with **Visual Studio Code**, similar to other data tools like **dbt**.
- **Support for Data Modeler Roles**:
  - **Visualizing database objects** and their relationships.
  - **Automating large model maintenance** using Python.
  - **Enabling custom automation for database modeling workflows**.

---

🚀 **Stay tuned for continuous improvements based on community feedback!** 🚀
