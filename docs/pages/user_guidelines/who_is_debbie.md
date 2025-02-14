# Who is Debbie?

Debbie is the command-line utility that powers **D-Blocks**, enabling seamless synchronization and maintenance of database objects in a Git-based workflow. Debbie acts as an **assistant**, helping both developers and CI/CD pipelines to maintain **database environments** efficiently.

### **Installation**
Debbie is included in the `d-blocks-core` package, which can be installed via **pip**.

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
3. **Install Debbie via pip**:
   ```bash
   pip install d-blocks-core
   ```

### **First Call**
Once installed, you can check if Debbie is working correctly by running:
```bash
debbie --help
```
This command provides an overview of available commands and options.