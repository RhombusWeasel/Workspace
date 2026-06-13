#Instructions for Workspace Agents:

Your task is to assist in the development of this project following the workflow and principles outlined below.

Check for a file in ~/.agents/user.md this is a place for you to store information about the user, you should always read this file first.  
If it doesn't exist then you should create it and try to gather some simple information about the user to begin with like their name and any syntax preferences they may have.
This file exists to allow you to share information about the user between sessions to personalize the experience and allow for more meaningful responses.

You should always check for any design documentation files in the current working directory, .agents/design.md or README.md files to try and understand the project you are working on.
An early `ls -l | grep design` can save a lot of time reading other files trying to understand something that may be documented.
If there is no .agents/design.md file then you should create it and document your understanding of the project there as you learn more.
Keep the .agents/design.md document up to date, it should contain a breif summary of the project as a whole, it's structure and any patterns used.  
This file should contain only the information required for quick getting started information to speed up induction for a new task.

You should also check for the existance of a tasks file like a tasks.md or a .agents/tasks.md file and ensure the task list is understood and kept up to date.
Again if there is no task list you should create .agents/tasks.md and maintain it to track your and the users progress.

We are using python with uv as our package manager/venv provider.  Please make sure all tests and library additions are run through uv.

Workflow for a change:

1. Read the design documentation and tasks to ascertain the changes required and present them to the user for confirmation.
2. Once the user has confirmed/clarified then add any modifications/updates to the task document so we can track our changes.
3. Make a branch for our changes so we can easily revert if we decide to change something after testing a feature.
4. Write the tests for the change.
5. Apply the change.
6. Ask the user to check and test the change.  Do not try and check the change yourself as the user may notice something you/they had not considered.

Below is an XML representation of the skills you have available, you can call the activate_skill tool at any time to get more detailed information about the skill and it's usage.
Skills are prefered over console commands where able as they can have additional access to various services etc.
