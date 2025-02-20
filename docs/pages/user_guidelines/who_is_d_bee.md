# Who is d-bee?

d-bee is the command-line utility that powers **d-blocks**, enabling seamless synchronization and maintenance of database objects in a Git-based workflow. d-bee acts as an **assistant**, helping both developers and CI/CD pipelines to maintain **database environments** efficiently.

### **Installation**
d-bee is included in the `d-blocks-core` package, which can be installed via **pip**.

#### **Prerequisites**
- Python 3.11+
- Virtual environment setup (recommended)

#### **Installation Steps**
1. **Create a virtual environment** (recommended for isolated installations):
   ```bash
   python -m venv dblocks-env
   ```
2. **Activate the virtual environment**:
   - On macOS/Linux:
     ```bash
     source dblocks-env/bin/activate
     ```
   - On Windows:
     ```bash
     dblocks-env\Scripts\activate
     ```
3. **Install d-bee via pip**:
   ```bash
   pip install d-blocks-core
   ```

### **First Call**
Once installed, you can check if d-bee is working correctly by running:
```bash
d-bee --help
```
This command provides an overview of available commands and options.