# csync 🚀

This is a fork of @anhvth’s repo: [https://github.com/anhvth/csync](https://github.com/anhvth/csync)

> Yet another modern Python wrapper for `rsync` to sync code between local and remote machines.

My workflow is simple: I write code on my local machine, sync it to an HPC server to run and collect results, create backups with Git, and sometimes sync the entire codebase to a remote development server for backup.

The original author no longer maintains the project, so I decided to fork it and maintain my own version.

## Worklogs

* 2026/02/03
   * Fixed the daemon spawn issue that previously did not work.
   * Added unit tests to support further development.
   * Added worktree and subagent setup for a smoother development workflow.
