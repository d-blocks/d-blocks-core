# Debbie's Project Structure

Debbie requires a standardized **directory structure** to store and maintain **database object definitions**. This structure is referred to as a **Debbie Project**.

### **Principles of Debbie’s Project Structure**
- All database objects are stored as individual files.
- File names reflect object names.
- File extensions indicate object types (e.g., `.tbl` for tables, `.vw` for views).

### **Object Naming Conventions**
| Object Type  | File Extension |
|--------------|----------------|
| Table        | `.tbl`         |
| View         | `.viw`         |
| Procedure    | `.pro`         |
| Macro        | `.mcr`         |
| Trigger      | `.trg`         |

### **Initializing a New Debbie Project**
To create a new project, navigate to an **empty Git repository** and run:
```bash
dbee init
```
If the directory is not already a **Git repository**, Debbie will initialize it for you.

As part of this setup, a **default configuration file (`dblocks.toml`)** is generated, which defines how Debbie interacts with database environments. Configuration details are discussed in the next section.
