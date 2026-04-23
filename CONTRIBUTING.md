# Contributing

## How to contribute

### Run unit tests
After changes made to the project, it's a good idea to run the unit tests before making a pull request. 


1. **Run SQL Server**  
   Make sure you have SQL Server running in your local machine. 
   Download and install SQL Server [here](https://www.microsoft.com/en-us/sql-server/sql-server-downloads), or you could use docker. Change `testapp/settings.py` to match your SQL Server login username and password.  
   
   ```
   docker run -e 'ACCEPT_EULA=Y' -e 'SA_PASSWORD=Placeholder' -p 1433:1433 -d mcr.microsoft.com/mssql/server:2019-latest
   ```
2. **Clone Django**   
   In `mssql-django` folder. 
   ```
   # Install your local mssql-django
   pip install -e .

   # The unit test suite are in `Django` folder, so we need to clone it
   git clone https://github.com/django/django.git --depth 1
   ```
   
3. **Install Tox**  
   ```
   # we use `tox` to run tests and install dependencies
   pip install tox
   ``` 
4. **Run Tox**  
   ```
   # eg. run django 3.1 tests with Python 3.7
   tox -e py37-django31
   ```

---
This project welcomes contributions and suggestions.  Most contributions require you to agree to a
Contributor License Agreement (CLA) declaring that you have the right to, and actually do, grant us
the rights to use your contribution. For details, visit https://cla.opensource.microsoft.com.

When you submit a pull request, a CLA bot will automatically determine whether you need to provide
a CLA and decorate the PR appropriately (e.g., status check, comment). Simply follow the instructions
provided by the bot. You will only need to do this once across all repos using our CLA.

This project has adopted the [Microsoft Open Source Code of Conduct](https://opensource.microsoft.com/codeofconduct/).
For more information see the [Code of Conduct FAQ](https://opensource.microsoft.com/codeofconduct/faq/) or
contact [opencode@microsoft.com](mailto:opencode@microsoft.com) with any additional questions or comments.
