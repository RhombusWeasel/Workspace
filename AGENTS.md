User instructions for this repo:

The project plan for this repo can be read in ./design_document.md.
The design document contains the task list for the project

We are using python with uv as our package manager/venv provider.  Please make sure all tests are run through uv.

Workflow for a change:

1. Read the design document and the tasks to ascertain the changes required and present them to the user for confirmation.
2. Once the user has confirmed/clarified then add any modifications to the task document so we can track our changes.
3. Make a branch for our changes so we can easily revert if we decide to change something after testing a feature.
4. Write the tests for the change.
5. Apply the change.
6. Ask the user to check and test the change.  Do not try and check the change yourself as this is a team we're in and the user wants to help out and may notice something you had not considered.

Additional Details:

  This is not a project that is in production currently, we do not require any kind of backwards compatibility layers.
  If a change would break something then fine, we can reset the db and run again, don't waste time trying to wrangle old data into a new system, cattle not pets.

  We are NOT taking shortcuts with this codebase.  NO placeholder code, NO "I'll implement this later" excuses, writing code is hard and it SHOULD be hard.  Nothing easy is worth having.  If there is a reason you might need to add a placeholder then stop execution immediately and inform the user of this intent so they may make that call.

  Test everything.  I want a folder called tests to have a suite for every system we create and those tests should cover every aspect of the spec.  If these tests do not all pass the task is not complete.  If you modify a file then make sure that any tests for that file still pass when you are done.  Do NOT rewrite any tests once created, that defeats the point of the tests and leads to creeping errors which are very hard to track down.  We are using Test Driven Development cycles here so Test file is written FIRST then we write the code to satisfy the tests.
