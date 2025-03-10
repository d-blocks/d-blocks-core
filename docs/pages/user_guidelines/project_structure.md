# Project Structure

d-bee requires a standardized **directory structure** to store and maintain **database object definitions**. This structure is referred to as a **d-bee Project**.

## **Principles of d-bee's Project Structure**

- All database objects are stored as individual files.
- File names reflect object names.
- File extensions indicate object types (e.g., `.tbl` for tables, `.vw` for views).

## **Object Naming Conventions**

Object Type   | File Extension
------------- | --------------
Table         | `.tab`
View          | `.viw`
Procedure     | `.pro`
Join Index    | `.jix`
Macro         | `.mcr`
Trigger       | `.trg`
Authorization | `.auth`
Generic SQL   | `.sql`
Generic BTEQ  | `.bteq`

## **Initializing a New d-bee Project**

To create a new project, navigate to an **empty Git repository** and run:

```bash
d-bee init
```

If the directory is not already a **Git repository**, d-bee will initialize it for you.

As part of this setup, a **default configuration file (`dblocks.toml`)** is generated, which defines how d-bee interacts with database environments. Configuration details are discussed in the next section.


## Suggested repository structure

To be defined later on.