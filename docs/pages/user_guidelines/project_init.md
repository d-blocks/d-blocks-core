# Feature: Project Initialization

## Overview

Project initialization is the first and most crucial step when deciding to maintain database code in Git. Whether you are working with existing database environments or starting a new implementation, **initializing a project** ensures a structured setup.

d-bee supports this process with a simple command:

```bash
d-bee init
```

This command sets up a **d-bee project** by initializing a Git repository (if not already done) and creating essential configuration files.

## Steps for Project Initialization

### **1\. Running `d-bee init`**

To initialize a d-bee project, navigate to the **root folder** where you want to initialize the Git repository and run:

```bash
d-bee init
```

### **2\. Choosing Configuration File Location**

After running the command, you will be asked whether the **default configuration files** should be:

- Stored **in the current directory** (to be version-controlled in Git).
- Created **in your home directory** (stored privately and outside version control).

🔹 If stored in the Git repository, configuration files will be shared among users working on the project.<br>
🔹 If stored in the home directory, they remain private to the local user.

_Note:_ Users can later move the configuration files between locations if needed. More details can be found in [Configuration Guide](configuration.md).

### **3\. Initializing the Git Repository (Optional)**

If the directory is not already a Git repository, d-bee will prompt you to initialize it. This includes:

- Running `git init`
- Configuring Git settings
- Creating a `.gitignore` file with recommended default settings

### **4\. Reviewing and Modifying Configuration**

Once initialization is complete, review the generated configuration files:

- **`dblocks.toml`** (public configuration, stored in Git if selected)
- **`.dblocks-secrets.toml`** (private configuration, stored securely in the home directory)

Modify them according to project needs by following the [Configuration Guide](configuration.md).

## Next Steps

After initializing the project:

- Adjust the configuration for your environments.
- Use `d-bee env-extract` to synchronize existing database objects to Git (see more detail in section [Feature: Extract Environment](extract.md)).
- Begin working with d-bee's features to manage database code efficiently.

--------------------------------------------------------------------------------

By following this structured setup, you ensure **best practices** and **smooth integration** of database code management within Git. 🚀
