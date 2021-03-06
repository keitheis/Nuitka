//     Copyright 2014, Kay Hayen, mailto:kay.hayen@gmail.com
//
//     Part of "Nuitka", an optimizing Python compiler that is compatible and
//     integrates with CPython, but also works on its own.
//
//     Licensed under the Apache License, Version 2.0 (the "License");
//     you may not use this file except in compliance with the License.
//     You may obtain a copy of the License at
//
//        http://www.apache.org/licenses/LICENSE-2.0
//
//     Unless required by applicable law or agreed to in writing, software
//     distributed under the License is distributed on an "AS IS" BASIS,
//     WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
//     See the License for the specific language governing permissions and
//     limitations under the License.
//
#ifndef __NUITKA_VARIABLES_LOCALS_H__
#define __NUITKA_VARIABLES_LOCALS_H__

class PyObjectLocalVariable
{
public:
    explicit PyObjectLocalVariable( PyObject *var_name, PyObject *object = NULL  )
    {
        this->var_name   = var_name;
        this->object     = object;
    }

    explicit PyObjectLocalVariable()
    {
        this->var_name   = NULL;
        this->object     = NULL;
    }

    ~PyObjectLocalVariable()
    {
        Py_XDECREF( this->object );
    }

    bool isInitialized() const
    {
        return this->object != NULL;
    }

private:

    PyObjectLocalVariable( const PyObjectLocalVariable &other ) { assert( false ); }

    PyObject *var_name;

public:

    PyObject *object;
};

#endif
