#     Copyright 2014, Kay Hayen, mailto:kay.hayen@gmail.com
#
#     Part of "Nuitka", an optimizing Python compiler that is compatible and
#     integrates with CPython, but also works on its own.
#
#     Licensed under the Apache License, Version 2.0 (the "License");
#     you may not use this file except in compliance with the License.
#     You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
#     Unless required by applicable law or agreed to in writing, software
#     distributed under the License is distributed on an "AS IS" BASIS,
#     WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#     See the License for the specific language governing permissions and
#     limitations under the License.
#
""" The code generation.

No language specifics at all are supposed to be present here. Instead it is
using primitives from the given generator to build code sequences (list of
strings).

As such this is the place that knows how to take a condition and two code
branches and make a code block out of it. But it doesn't contain any target
language syntax.
"""

from . import (
    Generator,
    Emission,
    Contexts,
)

from nuitka import (
    PythonOperators,
    Constants,
    Tracing,
    Options,
    Utils
)

from nuitka.__past__ import iterItems

def generateTupleCreationCode(to_name, elements, emit, context):
    if _areConstants(elements):
        Generator.getConstantAccessC(
            to_name  = to_name,
            constant = tuple(
                element.getConstant() for element in elements
            ),
            emit     = emit,
            context  = context
        )
    else:
        emit(
            "%s = PyTuple_New( %d );" % (
                to_name,
                len(elements)
            )
        )

        context.addCleanupTempName(to_name)

        element_name = context.allocateTempName("tuple_element")

        for count, element in enumerate(elements):
            generateExpressionCode(
                to_name    = element_name,
                expression = element,
                emit       = emit,
                context    = context
            )

            if not context.needsCleanup(element_name):
                emit("Py_INCREF( %s );" % element_name)
            else:
                context.removeCleanupTempName(element_name)

            emit(
                "PyTuple_SET_ITEM( %s, %d, %s );" % (
                    to_name,
                    count,
                    element_name
                )
            )


def generateListCreationCode(to_name, elements, emit, context):
    if _areConstants(elements):
        assert False
    else:
        emit(
            "%s = PyList_New( %d );" % (
                to_name,
                len(elements)
            )
        )

        context.addCleanupTempName(to_name)

        element_name = context.allocateTempName("list_element")

        for count, element in enumerate(elements):
            generateExpressionCode(
                to_name    = element_name,
                expression = element,
                emit       = emit,
                context    = context
            )

            if not context.needsCleanup(element_name):
                emit("Py_INCREF( %s );" % element_name)
            else:
                context.removeCleanupTempName(element_name)

            emit(
                "PyList_SET_ITEM( %s, %d, %s );" % (
                    to_name,
                    count,
                    element_name
                )
            )


def generateSetCreationCode(to_name, elements, emit, context):
    emit(
        "%s = PySet_New( NULL );" % (
            to_name,
        )
    )

    context.addCleanupTempName(to_name)

    element_name = context.allocateTempName("set_element")

    for count, element in enumerate(elements):
        generateExpressionCode(
            to_name    = element_name,
            expression = element,
            emit       = emit,
            context    = context
        )

        emit(
            "PySet_Add( %s, %s );" % (
                to_name,
                element_name
            )
        )

        if context.needsCleanup(element_name):
            emit("Py_DECREF( %s );" % element_name)
            context.removeCleanupTempName(element_name)


def generateDictionaryCreationCode(to_name, pairs, emit, context):
    emit(
        "%s = _PyDict_NewPresized( %d );" % (
            to_name,
            len(pairs)
        )
    )

    context.addCleanupTempName(to_name)

    dict_key_name = context.allocateTempName("dict_key")
    dict_value_name = context.allocateTempName("dict_value")

    # Strange as it is, CPython evalutes the key/value pairs strictly in order,
    # but for each pair, the value first.
    for count, pair in enumerate(pairs):
        generateExpressionCode(
            to_name    = dict_value_name,
            expression = pair.getValue(),
            emit       = emit,
            context    = context
        )

        generateExpressionCode(
            to_name    = dict_key_name,
            expression = pair.getKey(),
            emit       = emit,
            context    = context
        )

        emit(
            "PyDict_SetItem( %s, %s, %s );" % (
                to_name,
                dict_key_name,
                dict_value_name
            )
        )

        if context.needsCleanup(dict_value_name):
            emit("Py_DECREF( %s );" % dict_value_name)
            context.removeCleanupTempName(dict_value_name)

        if context.needsCleanup(dict_key_name):
            emit("Py_DECREF( %s );" % dict_key_name)
            context.removeCleanupTempName(dict_key_name)


def generateConditionCode(condition, emit, context, inverted = False,
                          allow_none = False):
    # The complexity is needed to avoid unnecessary complex generated C++, so
    # e.g. inverted is typically a branch inside every optimizable case.
    # pylint: disable=R0912,R0915,R0914

    if condition is None and allow_none:
        # TODO: Allow none, why?

        Generator.getGotoCode(context.getTrueBranchTarget(), emit)
    elif condition.isExpressionConstantRef():
        value = condition.getConstant()

        if inverted:
            value = not value
            inverted = False

        if value:
            Generator.getGotoCode(context.getTrueBranchTarget(), emit)
        else:
            Generator.getGotoCode(context.getFalseBranchTarget(), emit)
    elif condition.isExpressionComparison():
        left_name = context.allocateTempName("compare_left")

        generateExpressionCode(
            to_name    = left_name,
            expression = condition.getLeft(),
            emit       = emit,
            context    = context
        )

        right_name = context.allocateTempName("compare_right")

        generateExpressionCode(
            to_name    = right_name,
            expression = condition.getRight(),
            emit       = emit,
            context    = context
        )

        comparator = condition.getComparator()

        # Do not allow this, can be expected to be optimized away.
        assert not inverted or \
              comparator not in PythonOperators.comparison_inversions, \
                 condition

        # If inverted, lets just switch the targets temporarily.
        if inverted:
            true_target = context.getTrueBranchTarget()
            false_target = context.getFalseBranchTarget

            context.setTrueBranchTarget(false_target)
            context.setFalseBranchTarget(true_target)

        Generator.getComparisonExpressionBoolCode(
            comparator      = comparator,
            left_name       = left_name,
            right_name      = right_name,
            emit            = emit,
            context         = context
        )

        if inverted:
            context.setTrueBranchTarget(true_target)
            context.setFalseBranchTarget(false_target)
    elif condition.isExpressionOperationNOT():
        # If not inverted, lets just switch the targets temporarily.
        if not inverted:
            true_target = context.getTrueBranchTarget()
            false_target = context.getFalseBranchTarget()

            context.setTrueBranchTarget(false_target)
            context.setFalseBranchTarget(true_target)

        generateConditionCode(
            condition = condition.getOperand(),
            emit      = emit,
            context   = context
        )

        if not inverted:
            context.setTrueBranchTarget(true_target)
            context.setFalseBranchTarget(false_target)
    elif condition.isExpressionConditional():
        expression_yes = condition.getExpressionYes()
        expression_no = condition.getExpressionNo()

        condition = condition.getCondition()

        old_true_target = context.getTrueBranchTarget()
        old_false_target = context.getFalseBranchTarget()

        select_true = context.allocateLabel("select_true")
        select_false = context.allocateLabel("select_false")

        # TODO: Could be avoided in some cases.
        select_end = context.allocateLabel("select_end")

        context.setTrueBranchTarget(select_true)
        context.setFalseBranchTarget(select_false)

        generateConditionCode(
            condition = condition,
            emit      = emit,
            context   = context,
        )

        context.setTrueBranchTarget(old_true_target)
        context.setFalseBranchTarget(old_false_target)

        Generator.getLabelCode(select_true,emit)
        generateConditionCode(
            condition = expression_yes,
            emit      = emit,
            context   = context,
        )
        Generator.getGotoCode(select_end, emit)
        Generator.getLabelCode(select_false,emit)
        generateConditionCode(
            condition = expression_no,
            emit      = emit,
            context   = context,
        )
        Generator.getLabelCode(select_end,emit)
    elif condition.isExpressionBuiltinHasattr():
        source_name = context.allocateTempName("hasattr_source")
        attr_name = context.allocateTempName("hasattr_attr")

        generateExpressionCode(
            to_name    = source_name,
            expression = condition.getLookupSource(),
            emit       = emit,
            context    = context
        )
        generateExpressionCode(
            to_name    = attr_name,
            expression = condition.getAttribute(),
            emit       = emit,
            context    = context
        )

        Generator.getAttributeCheckBoolCode(
            source_name = source_name,
            attr_name   = attr_name,
            emit        = emit,
            context     = context
        )
    elif condition.isExpressionBuiltinIsinstance():
        assert not inverted

        inst_name = context.allocateTempName("isinstance_inst")
        cls_name = context.allocateTempName("isinstance_cls")

        generateExpressionCode(
            to_name    = inst_name,
            expression = condition.getInstance(),
            emit       = emit,
            context    = context
        )
        generateExpressionCode(
            to_name    = cls_name,
            expression = condition.getCls(),
            emit       = emit,
            context    = context
        )

        Generator.getBuiltinIsinstanceBoolCode(
            inst_name = inst_name,
            cls_name  = cls_name,
            emit      = emit,
            context   = context
        )
    else:
        # TODO: Temp keeper assigments
        condition_name = context.allocateTempName("cond_value")
        truth_name = context.allocateTempName("cond_truth", "int")

        generateExpressionCode(
            to_name    = condition_name,
            expression = condition,
            emit       = emit,
            context    = context
        )

        if inverted:
            Generator.getConditionCheckFalseCode(
                to_name    = truth_name,
                value_name = condition_name,
                emit       = emit,
                context    = context
            )
        else:
            Generator.getConditionCheckTrueCode(
                to_name    = truth_name,
                value_name = condition_name,
                emit       = emit,
                context    = context
            )

        Generator.getErrorExitBoolCode(
            condition = "%s == -1" % truth_name,
            quick_exception = None,
            emit      = emit,
            context   = context
        )

        Generator.getReleaseCode(
            release_name = condition_name,
            emit         = emit,
            context      = context
        )

        Generator.getBranchingCode(
            condition = "%s == 1" % truth_name,
            emit      = emit,
            context   = context
        )


def generateFunctionCallCode(to_name, call_node, emit, context):
    assert call_node.getFunction().isExpressionFunctionCreation()

    function_body = call_node.getFunction().getFunctionRef().getFunctionBody()
    function_identifier = function_body.getCodeName()

    argument_values = call_node.getArgumentValues()

    arg_names = []
    for count, arg_value in enumerate(argument_values):
        arg_name = context.allocateTempName("dircall_arg%d" % (count+1))

        generateExpressionCode(
            to_name    = arg_name,
            expression = arg_value,
            emit       = emit,
            context    = context
        )

        arg_names.append(arg_name)

    Generator.getDirectFunctionCallCode(
        to_name             = to_name,
        function_identifier = function_identifier,
        arg_names           = arg_names,
        closure_variables   = function_body.getClosureVariables(),
        emit                = emit,
        context             = context
    )

_generated_functions = {}



def generateFunctionCreationCode(to_name, function_body, defaults, kw_defaults,
                                  annotations, emit, context):
    assert function_body.needsCreation(), function_body

    parameters = function_body.getParameters()

    if kw_defaults:
        kw_defaults_name = context.allocateTempName("kw_defaults")

        assert not kw_defaults.isExpressionConstantRef() or \
               not kw_defaults.getConstant() == {}, kw_defaults.getConstant()

        generateExpressionCode(
            to_name    = kw_defaults_name,
            expression = kw_defaults,
            emit       = emit,
            context    = context
        )
    else:
        kw_defaults_name = None

    if defaults:
        defaults_name = context.allocateTempName("defaults")

        generateTupleCreationCode(
            to_name  = defaults_name,
            elements = defaults,
            emit     = emit,
            context  = context
        )
    else:
        defaults_name = None

    if annotations:
        annotations_name = context.allocateTempName("annotations")

        generateExpressionCode(
            to_name    = annotations_name,
            expression = annotations,
            emit       = emit,
            context    = context,
        )
    else:
        annotations_name = None

    function_identifier = function_body.getCodeName()

    maker_code = Generator.getFunctionMakerCode(
        function_name       = function_body.getFunctionName(),
        function_qualname   = function_body.getFunctionQualname(),
        function_identifier = function_identifier,
        parameters          = parameters,
        local_variables     = function_body.getLocalVariables(),
        closure_variables   = function_body.getClosureVariables(),
        defaults_name       = defaults_name,
        kw_defaults_name    = kw_defaults_name,
        annotations_name    = annotations_name,
        source_ref          = function_body.getSourceReference(),
        function_doc        = function_body.getDoc(),
        is_generator        = function_body.isGenerator(),
        emit                = emit,
        context             = context
    )

    context.addHelperCode(function_identifier, maker_code)

    function_decl = Generator.getFunctionMakerDecl(
        function_identifier = function_body.getCodeName(),
        defaults_name       = defaults_name,
        kw_defaults_name    = kw_defaults_name,
        annotations_name    = annotations_name,
        closure_variables   = function_body.getClosureVariables()
    )

    if function_body.getClosureVariables() and not function_body.isGenerator():
        function_decl += "\n"

        function_decl += Generator.getFunctionContextDefinitionCode(
            context              = context,
            function_identifier  = function_body.getCodeName(),
            closure_variables    = function_body.getClosureVariables(),
        )

    context.addDeclaration(function_identifier, function_decl)

    Generator.getFunctionCreationCode(
        to_name             = to_name,
        function_identifier = function_body.getCodeName(),
        defaults_name       = defaults_name,
        kw_defaults_name    = kw_defaults_name,
        annotations_name    = annotations_name,
        closure_variables   = function_body.getClosureVariables(),
        emit                = emit,
        context             = context
    )

    Generator.getReleaseCode(
        release_name = annotations_name,
        emit         = emit,
        context      = context
    )

    Generator.getErrorExitCode(
        check_name = to_name,
        emit       = emit,
        context    = context
    )

def generateFunctionBodyCode(function_body, context):
    function_identifier = function_body.getCodeName()

    if function_identifier in _generated_functions:
        return _generated_functions[ function_identifier ]

    if function_body.needsCreation():
        function_context = Contexts.PythonFunctionCreatedContext(
            parent   = context,
            function = function_body
        )
    else:
        function_context = Contexts.PythonFunctionDirectContext(
            parent   = context,
            function = function_body
        )

    # TODO: Generate both codes, and base direct/etc. decisions on context.
    function_codes = generateStatementSequenceCode(
        statement_sequence = function_body.getBody(),
        allow_none         = True,
        context            = function_context
    )

    function_codes = function_codes or []

    parameters = function_body.getParameters()

    needs_exception_exit = function_body.mayRaiseException(BaseException)
    needs_generator_return = function_body.needsGeneratorReturnExit()

    if function_body.isGenerator():
        function_code = Generator.getGeneratorFunctionCode(
            context                = function_context,
            function_name          = function_body.getFunctionName(),
            function_identifier    = function_identifier,
            parameters             = parameters,
            closure_variables      = function_body.getClosureVariables(),
            user_variables         = function_body.getUserLocalVariables(),
            temp_variables         = function_body.getTempVariables(),
            source_ref             = function_body.getSourceReference(),
            function_codes         = function_codes,
            function_doc           = function_body.getDoc(),
            needs_exception_exit   = needs_exception_exit,
            needs_generator_return = needs_generator_return
        )
    else:
        function_code = Generator.getFunctionCode(
            context                = function_context,
            function_name          = function_body.getFunctionName(),
            function_identifier    = function_identifier,
            parameters             = parameters,
            closure_variables      = function_body.getClosureVariables(),
            user_variables         = function_body.getUserLocalVariables(),
            temp_variables         = function_body.getTempVariables(),
            function_codes         = function_codes,
            function_doc           = function_body.getDoc(),
            needs_exception_exit   = needs_exception_exit,
            file_scope             = Generator.getExportScopeCode(
                cross_module = function_body.isCrossModuleUsed()
            )
        )



    return function_code


def generateComparisonExpressionCode(to_name, comparison_expression, emit,
                                     context):
    left_name = context.allocateTempName("compexpr_left")
    right_name = context.allocateTempName("compexpr_right")

    generateExpressionCode(
        to_name    = left_name,
        expression = comparison_expression.getLeft(),
        emit       = emit,
        context    = context
    )
    generateExpressionCode(
        to_name    = right_name,
        expression = comparison_expression.getRight(),
        emit       = emit,
        context    = context
    )

    Generator.getComparisonExpressionCode(
        to_name         = to_name,
        comparator      = comparison_expression.getComparator(),
        left_name       = left_name,
        right_name      = right_name,
        emit            = emit,
        context         = context
    )


def _areConstants(expressions):
    for expression in expressions:
        if not expression.isExpressionConstantRef():
            return False

        if expression.isMutable():
            return False
    else:
        return True

def generateSliceRangeIdentifier(lower, upper, scope, emit, context):
    lower_name = context.allocateTempName(
        scope + "slicedel_index_lower",
        "Py_ssize_t"
    )
    upper_name = context.allocateTempName(
        scope + "_index_upper",
        "Py_ssize_t"
    )

    def isSmallNumberConstant(node):
        value = node.getConstant()

        if Constants.isNumberConstant( value ):
            return abs(int(value)) < 2**63-1
        else:
            return False

    if lower is None:
        Generator.getMinIndexCode(
            to_name = lower_name,
            emit    = emit
        )
    elif lower.isExpressionConstantRef() and isSmallNumberConstant(lower):
        Generator.getIndexValueCode(
            to_name = lower_name,
            value   = int(lower.getConstant()),
            emit    = emit
        )
    else:
        value_name = context.allocateTempName(scope + "_lower_index_value")

        generateExpressionCode(
            to_name    = value_name,
            expression = lower,
            emit       = emit,
            context    = context
        )

        Generator.getIndexCode(
            to_name    = lower_name,
            value_name = value_name,
            emit       = emit,
            context    = context
        )

    if upper is None:
        Generator.getMaxIndexCode(
            to_name = upper_name,
            emit    = emit
        )
    elif upper.isExpressionConstantRef() and isSmallNumberConstant(upper):
        Generator.getIndexValueCode(
            to_name = upper_name,
            value   = int(upper.getConstant()),
            emit    = emit
        )
    else:
        value_name = context.allocateTempName(scope + "_upper_index_value")

        generateExpressionCode(
            to_name    = value_name,
            expression = upper,
            emit       = emit,
            context    = context
        )

        Generator.getIndexCode(
            to_name    = upper_name,
            value_name = value_name,
            emit       = emit,
            context    = context
        )

    return lower_name, upper_name

_slicing_available = Utils.python_version < 300

def decideSlicing(lower, upper):
    return _slicing_available and                       \
           (lower is None or lower.isIndexable()) and \
           (upper is None or upper.isIndexable())

def generateSubscriptLookupCode(to_name, expression, emit, context):
    subscribed_name = context.allocateTempName("subscr_target")
    subscript_name = context.allocateTempName("subscr_subscript")

    generateExpressionCode(
        to_name    = subscribed_name,
        expression = expression.getLookupSource(),
        emit       = emit,
        context    = context
    )

    generateExpressionCode(
        to_name    = subscript_name,
        expression = expression.getSubscript(),
        emit       = emit,
        context    = context
    )

    return Generator.getSubscriptLookupCode(
        to_name         = to_name,
        subscribed_name = subscribed_name,
        subscript_name  = subscript_name,
        emit            = emit,
        context         = context
    )


def generateSliceLookupCode(to_name, expression, emit, context):
    lower = expression.getLower()
    upper = expression.getUpper()

    if decideSlicing(lower, upper):
        lower_name, upper_name = generateSliceRangeIdentifier(
            lower   = lower,
            upper   = upper,
            scope   = "slice",
            emit    = emit,
            context = context
        )

        source_name = context.allocateTempName("slice_source")

        generateExpressionCode(
            to_name     = source_name,
            expression  = expression.getLookupSource(),
            emit        = emit,
            context     = context
        )

        Generator.getSliceLookupIndexesCode(
            to_name     = to_name,
            source_name = source_name,
            lower_name  = lower_name,
            upper_name  = upper_name,
            emit        = emit,
            context     = context
        )
    else:
        if _slicing_available:
            source_name, lower_name, upper_name = generateExpressionsCode(
                names       = ("slice_source", "slice_lower", "slice_upper"),
                expressions = (
                    expression.getLookupSource(),
                    expression.getLower(),
                    expression.getUpper()
                ),
                emit        = emit,
                context     = context
            )

            Generator.getSliceLookupCode(
                to_name     = to_name,
                source_name = source_name,
                lower_name  = lower_name,
                upper_name  = upper_name,
                emit        = emit,
                context     = context
            )
        else:
            subscript_name = context.allocateTempName("slice_subscript")

            subscribed_name, lower_name, upper_name = generateExpressionsCode(
                names       = (
                    "slice_target", "slice_lower", "slice_upper"
                ),
                expressions = (
                    expression.getLookupSource(),
                    expression.getLower(),
                    expression.getUpper()
                ),
                emit        = emit,
                context     = context
            )

            # TODO: The decision should be done during optimization, so
            # _slicing_available should play no role at all.
            Generator.getSliceObjectCode(
                to_name    = subscript_name,
                lower_name = lower_name,
                upper_name = upper_name,
                step_name  = None,
                emit       = emit,
                context    = context
            )

            return Generator.getSubscriptLookupCode(
                to_name         = to_name,
                subscribed_name = subscribed_name,
                subscript_name  = subscript_name,
                emit            = emit,
                context         = context
            )


def generateCallCode(to_name, call_node, emit, context):
    called_name = context.allocateTempName("called")

    generateExpressionCode(
        to_name    = called_name,
        expression = call_node.getCalled(),
        emit       = emit,
        context    = context
    )

    call_args = call_node.getCallArgs()

    call_kw = call_node.getCallKw()

    if call_kw.isExpressionConstantRef() and call_kw.getConstant() == {}:
        if call_args.isExpressionMakeTuple():
            call_arg_names = []

            for call_arg_element in call_args.getElements():
                call_arg_name = context.allocateTempName("call_arg_element")

                generateExpressionCode(
                    to_name    = call_arg_name,
                    expression = call_arg_element,
                    emit       = emit,
                    context    = context,
                )

                call_arg_names.append(call_arg_name)

            assert call_arg_names

            Generator.getCallCodePosArgsQuickC(
                to_name     = to_name,
                called_name = called_name,
                arg_names   = call_arg_names,
                emit        = emit,
                context     = context
            )
        elif call_args.isExpressionConstantRef():
            call_args_value = call_args.getConstant()
            assert type(call_args_value) is tuple

            call_arg_names = []

            for call_arg_element in call_args_value:
                call_arg_name = context.allocateTempName("call_arg_element")

                Generator.getConstantAccessC(
                    to_name    = call_arg_name,
                    constant   = call_arg_element,
                    emit       = emit,
                    context    = context,
                )

                call_arg_names.append(call_arg_name)

            if call_arg_names:
                Generator.getCallCodePosArgsQuickC(
                    to_name     = to_name,
                    called_name = called_name,
                    arg_names   = call_arg_names,
                    emit        = emit,
                    context     = context
                )
            else:
                Generator.getCallCodeNoArgsC(
                    to_name     = to_name,
                    called_name = called_name,
                    emit        = emit,
                    context     = context
                )
        else:
            args_name = context.allocateTempName("call_pos")

            generateExpressionCode(
                to_name    = args_name,
                expression = call_args,
                emit       = emit,
                context    = context
            )

            Generator.getCallCodePosArgsC(
                to_name     = to_name,
                called_name = called_name,
                args_name   = args_name,
                emit        = emit,
                context     = context
            )
    else:
        if call_args.isExpressionConstantRef() and \
           call_args.getConstant() == ():
            call_kw_name = context.allocateTempName("call_kw")

            generateExpressionCode(
                to_name    = call_kw_name,
                expression = call_kw,
                emit       = emit,
                context    = context
            )

            Generator.getCallCodeKeywordArgs(
                to_name        = to_name,
                called_name    = called_name,
                call_kw_name   = call_kw_name,
                emit           = emit,
                context        = context
            )
        else:
            call_args_name = context.allocateTempName("call_pos")

            generateExpressionCode(
                to_name    = call_args_name,
                expression = call_args,
                emit       = emit,
                context    = context
            )

            call_kw_name = context.allocateTempName("call_kw")

            generateExpressionCode(
                to_name    = call_kw_name,
                expression = call_kw,
                emit       = emit,
                context    = context
            )

            Generator.getCallCodePosKeywordArgs(
                to_name        = to_name,
                called_name    = called_name,
                call_args_name = call_args_name,
                call_kw_name   = call_kw_name,
                emit           = emit,
                context        = context
            )


def generateBuiltinLocalsCode(to_name, locals_node, emit, context):
    provider = locals_node.getParentVariableProvider()

    return Generator.getLoadLocalsCode(
        to_name  = to_name,
        provider = provider,
        mode     = provider.getLocalsMode(),
        emit     = emit,
        context  = context
    )

def _generateExpressionCode(to_name, expression, emit, context, allow_none):
    # This is a dispatching function with a branch per expression node type, and
    # therefore many statements even if every branch is small
    # pylint: disable=R0912,R0915

    if expression is None and allow_none:
        return None

    # Make sure we don't generate code twice for any node, this uncovers bugs
    # where nodes are shared in the tree, which is not allowed.
    assert not hasattr(expression, "code_generated"), expression
    expression.code_generated = True

    context.setSourceReference(expression.getSourceReference())

    def makeExpressionCode(to_name, expression, allow_none = False):
        if allow_none and expression is None:
            return None

        generateExpressionCode(
            to_name    = to_name,
            expression = expression,
            emit       = emit,
            context    = context
        )

    def generateCAPIObjectCodeommon(to_name, capi, arg_desc, ref_count, emit,
                                     context, none_null = False):
        arg_names = []

        for arg_name, arg_expression in arg_desc:
            if arg_expression is None and none_null:
                arg_names.append("NULL")
            else:
                arg_name = context.allocateTempName(arg_name)

                makeExpressionCode(
                    to_name    = arg_name,
                    expression = arg_expression
                )

                arg_names.append(arg_name)

        Generator.getCAPIObjectCode(
            to_name   = to_name,
            capi      = capi,
            arg_names = arg_names,
            ref_count = ref_count,
            emit      = emit,
            context   = context
        )

    def generateCAPIObjectCode(to_name, capi, arg_desc, emit, context,
                               none_null = False):
        generateCAPIObjectCodeommon(
            to_name   = to_name,
            capi      = capi,
            arg_desc  = arg_desc,
            ref_count = 1,
            emit      = emit,
            context   = context,
            none_null = none_null
        )

    def generateCAPIObjectCode0(to_name, capi, arg_desc, emit, context,
                                none_null = False):
        generateCAPIObjectCodeommon(
            to_name   = to_name,
            capi      = capi,
            arg_desc  = arg_desc,
            ref_count = 0,
            emit      = emit,
            context   = context,
            none_null = none_null
        )


    if not expression.isExpression():
        Tracing.printError( "No expression %r" % expression )

        expression.dump()
        assert False, expression

    if expression.isExpressionVariableRef():
        if expression.getVariable() is None:
            Tracing.printError("Illegal variable reference, not resolved.")

            expression.dump()
            assert False, (
                expression.getSourceReference(),
                expression.getVariableName()
            )

        Generator.getVariableAccessCode(
            to_name  = to_name,
            variable = expression.getVariable(),
            emit     = emit,
            context  = context
        )
    elif expression.isExpressionTempVariableRef():
        Generator.getVariableAccessCode(
            to_name  = to_name,
            variable = expression.getVariable(),
            emit     = emit,
            context  = context
        )
    elif expression.isExpressionConstantRef():
        Generator.getConstantAccessC(
            to_name  = to_name,
            constant = expression.getConstant(),
            emit     = emit,
            context  = context
        )
    elif expression.isExpressionAttributeLookup():
        source_name = context.allocateTempName("source_name")

        makeExpressionCode(
            to_name    = source_name,
            expression = expression.getLookupSource()
        )

        Generator.getAttributeLookupCode(
            to_name        = to_name,
            source_name    = source_name,
            attribute_name = expression.getAttributeName(),
            emit           = emit,
            context        = context
        )
    elif expression.isExpressionSubscriptLookup():
        generateSubscriptLookupCode(
            to_name    = to_name,
            expression = expression,
            emit       = emit,
            context    = context
        )
    elif expression.isExpressionSliceLookup():
        generateSliceLookupCode(
            to_name    = to_name,
            expression = expression,
            emit       = emit,
            context    = context
        )
    elif expression.isExpressionSliceObject():
        lower_name, upper_name, step_name = generateExpressionsCode(
            expressions = (
                expression.getLower(),
                expression.getUpper(),
                expression.getStep()
            ),
            names       = (
                "sliceobj_lower", "sliceobj_upper", "sliceobj_step"
            ),
            emit        = emit,
            context     = context
        )

        Generator.getSliceObjectCode(
            to_name    = to_name,
            lower_name = lower_name,
            upper_name = upper_name,
            step_name  = step_name,
            emit       = emit,
            context    = context
        )
    elif expression.isExpressionCall():
        generateCallCode(
            to_name   = to_name,
            call_node = expression,
            emit      = emit,
            context   = context
        )
    elif expression.isExpressionFunctionCall():
        generateFunctionCallCode(
            to_name   = to_name,
            call_node = expression,
            emit      = emit,
            context   = context
        )
    elif expression.isExpressionBuiltinNext1():
        value_name = context.allocateTempName("next1_arg")

        makeExpressionCode(
            to_name    = value_name,
            expression = expression.getValue()
        )

        Generator.getBuiltinNext1Code(
            to_name = to_name,
            value   = value_name,
            emit    = emit,
            context = context
        )
    elif expression.isExpressionBuiltinNext2():
        generateCAPIObjectCode(
            to_name  = to_name,
            capi     = "BUILTIN_NEXT2",
            arg_desc = (
                ("next_arg", expression.getIterator()),
                ("next_default", expression.getDefault()),
            ),
            emit     = emit,
            context  = context
        )
    elif expression.isExpressionSpecialUnpack():
        value_name = context.allocateTempName("unpack")

        makeExpressionCode(
            to_name    = value_name,
            expression = expression.getValue()
        )

        Generator.getUnpackNextCode(
            to_name = to_name,
            value   = value_name,
            count   = expression.getCount(),
            emit    = emit,
            context = context
        )
    elif expression.isExpressionBuiltinGlobals():
        Generator.getLoadGlobalsCode(
            to_name = to_name,
            emit    = emit,
            context = context
        )
    elif expression.isExpressionImportModule():
        generateImportModuleCode(
            to_name    = to_name,
            expression = expression,
            emit       = emit,
            context    = context
        )
    elif expression.isExpressionBuiltinImport():
        generateBuiltinImportCode(
            to_name    = to_name,
            expression = expression,
            emit       = emit,
            context    = context
        )
    elif expression.isExpressionImportModuleHard():
        Generator.getImportModuleHardCode(
            to_name     = to_name,
            module_name = expression.getModuleName(),
            import_name = expression.getImportName(),
            emit        = emit,
            context     = context
        )
    elif expression.isExpressionFunctionCreation():
        generateFunctionCreationCode(
            to_name        = to_name,
            function_body  = expression.getFunctionRef().getFunctionBody(),
            defaults       = expression.getDefaults(),
            kw_defaults    = expression.getKwDefaults(),
            annotations    = expression.getAnnotations(),
            emit           = emit,
            context        = context
        )
    elif expression.isExpressionCaughtExceptionTypeRef():
        Generator.getExceptionCaughtTypeCode(
            to_name = to_name,
            emit    = emit,
            context = context
        )
    elif expression.isExpressionCaughtExceptionValueRef():
        Generator.getExceptionCaughtValueCode(
            to_name = to_name,
            emit    = emit,
            context = context
        )
    elif expression.isExpressionCaughtExceptionTracebackRef():
        Generator.getExceptionCaughtTracebackCode(
            to_name = to_name,
            emit    = emit,
            context = context
        )
    elif expression.isExpressionBuiltinExceptionRef():
        Generator.getExceptionRefCode(
            to_name        = to_name,
            exception_type = expression.getExceptionName(),
            emit           = emit,
            context        = context
        )
    elif expression.isExpressionBuiltinAnonymousRef():
        Generator.getBuiltinAnonymousRefCode(
            to_name      = to_name,
            builtin_name = expression.getBuiltinName(),
            emit         = emit,
            context      = context
        )
    elif expression.isExpressionBuiltinMakeException():
        exception_arg_names = []

        for exception_arg in expression.getArgs():
            exception_arg_name = context.allocateTempName("make_exception_arg")

            makeExpressionCode(
                to_name    = exception_arg_name,
                expression = exception_arg
            )

            exception_arg_names.append(exception_arg_name)

        Generator.getMakeBuiltinExceptionCode(
            to_name        = to_name,
            exception_type = expression.getExceptionName(),
            arg_names      = exception_arg_names,
            emit           = emit,
            context        = context
        )
    elif expression.isExpressionOperationBinary():
        left_arg_name = context.allocateTempName("binop_left")
        right_arg_name = context.allocateTempName("binop_right")

        makeExpressionCode(
            to_name    = left_arg_name,
            expression = expression.getLeft()
        )
        makeExpressionCode(
            to_name    = right_arg_name,
            expression = expression.getRight()
        )

        Generator.getOperationCode(
            to_name   = to_name,
            operator  = expression.getOperator(),
            arg_names = (left_arg_name, right_arg_name),
            emit      = emit,
            context   = context
        )
    elif expression.isExpressionOperationUnary():
        arg_name = context.allocateTempName("unary_arg")

        makeExpressionCode(
            to_name    = arg_name,
            expression = expression.getOperand()
        )

        Generator.getOperationCode(
            to_name   = to_name,
            operator  = expression.getOperator(),
            arg_names = (arg_name,),
            emit      = emit,
            context   = context
        )
    elif expression.isExpressionComparison():
        generateComparisonExpressionCode(
            to_name               = to_name,
            comparison_expression = expression,
            emit                  = emit,
            context               = context
        )
    elif Utils.python_version < 300 and expression.isExpressionBuiltinStr():
        generateCAPIObjectCode(
            to_name  = to_name,
            capi     = "PyObject_Str",
            arg_desc = (
                ("str_arg", expression.getValue()),
            ),
            emit     = emit,
            context  = context
        )
    elif (
           Utils.python_version < 300 and \
           expression.isExpressionBuiltinUnicode()
        ) or (
           Utils.python_version >= 300 and \
           expression.isExpressionBuiltinStr()
        ):
        encoding = expression.getEncoding()
        errors = expression.getErrors()

        if encoding is None and errors is None:
            generateCAPIObjectCode(
                to_name  = to_name,
                capi     = "PyObject_Unicode",
                arg_desc = (
                    (
                        "str_arg" if Utils.python_version < 300 \
                          else "unicode_arg",
                        expression.getValue()
                    ),
                ),
                emit     = emit,
                context  = context
            )
        else:
            generateCAPIObjectCode(
                to_name   = to_name,
                capi      = "TO_UNICODE3",
                arg_desc = (
                    ("unicode_arg", expression.getValue()),
                    ("unicode_encoding", encoding),
                    ("unicode_errors", errors),
                ),
                emit      = emit,
                none_null = True,
                context   = context
            )

    elif expression.isExpressionBuiltinIter1():
        generateCAPIObjectCode(
            to_name  = to_name,
            capi     = "MAKE_ITERATOR",
            arg_desc = (
                ( "iter_arg", expression.getValue() ),
            ),
            emit     = emit,
            context  = context
        )
    elif expression.isExpressionBuiltinIter2():
        generateCAPIObjectCode(
            to_name  = to_name,
            capi     = "BUILTIN_ITER2",
            arg_desc = (
                ("iter_callable", expression.getCallable()),
                ("iter_sentinel", expression.getSentinel()),
            ),
            emit     = emit,
            context  = context
        )
    elif expression.isExpressionBuiltinType1():
        generateCAPIObjectCode(
            to_name  = to_name,
            capi     = "BUILTIN_TYPE1",
            arg_desc = (
                ( "type_arg", expression.getValue() ),
            ),
            emit     = emit,
            context  = context
        )
    elif expression.isExpressionBuiltinIsinstance():
        generateCAPIObjectCode0(
            to_name  = to_name,
            capi     = "BUILTIN_ISINSTANCE",
            arg_desc = (
                ("isinstance_inst", expression.getInstance()),
                ("isinstance_cls", expression.getCls()),
            ),
            emit     = emit,
            context  = context
        )
    elif expression.isExpressionSpecialAttributeLookup():
        source_name = context.allocateTempName("attr_source")

        makeExpressionCode(
            to_name    = source_name,
            expression = expression.getLookupSource()
        )


        Generator.getSpecialAttributeLookupCode(
            to_name     = to_name,
            source_name = source_name,
            attr_name   = Generator.getConstantCode(
                context  = context,
                constant = expression.getAttributeName()
            ),
            emit        = emit,
            context     = context
        )
    elif expression.isExpressionBuiltinHasattr():
        generateCAPIObjectCode0(
            to_name  = to_name,
            capi     = "BUILTIN_HASATTR",
            arg_desc = (
                ("hasattr_value", expression.getLookupSource()),
                ("hasattr_attr", expression.getAttribute()),
            ),
            emit     = emit,
            context  = context
        )
    elif expression.isExpressionBuiltinGetattr():
        generateCAPIObjectCode(
            to_name   = to_name,
            capi      = "BUILTIN_GETATTR",
            arg_desc  = (
                ("getattr_target", expression.getLookupSource()),
                ("getattr_attr", expression.getAttribute()),
                ("getattr_default", expression.getDefault()),
            ),
            emit      = emit,
            none_null = True,
            context   = context
        )
    elif expression.isExpressionBuiltinSetattr():
        generateCAPIObjectCode0(
            to_name   = to_name,
            capi      = "BUILTIN_SETATTR",
            arg_desc  = (
                ("setattr_target", expression.getLookupSource()),
                ("setattr_attr", expression.getAttribute()),
                ("setattr_value", expression.getValue()),
            ),
            emit      = emit,
            context   = context
        )
    elif expression.isExpressionBuiltinRef():
        Generator.getBuiltinRefCode(
            to_name      = to_name,
            builtin_name = expression.getBuiltinName(),
            emit         = emit,
            context      = context
        )
    elif expression.isExpressionBuiltinOriginalRef():
        assert not expression.isExpressionBuiltinRef()

        Generator.getBuiltinOriginalRefCode(
            to_name      = to_name,
            builtin_name = expression.getBuiltinName(),
            emit         = emit,
            context      = context
        )
    elif expression.isExpressionMakeTuple():
        generateTupleCreationCode(
            to_name  = to_name,
            elements = expression.getElements(),
            emit     = emit,
            context  = context
        )
    elif expression.isExpressionMakeList():
        generateListCreationCode(
            to_name  = to_name,
            elements = expression.getElements(),
            emit     = emit,
            context  = context
        )
    elif expression.isExpressionMakeSet():
        generateSetCreationCode(
            to_name  = to_name,
            elements = expression.getElements(),
            emit     = emit,
            context  = context
        )
    elif expression.isExpressionMakeDict():
        assert expression.getPairs()

        generateDictionaryCreationCode(
            to_name = to_name,
            pairs   = expression.getPairs(),
            emit    = emit,
            context = context
        )
    elif expression.isExpressionBuiltinInt():
        value = expression.getValue()
        base = expression.getBase()

        assert value is not None

        if base is None:
            generateCAPIObjectCode(
                to_name  = to_name,
                capi     = "PyNumber_Int",
                arg_desc = (
                    ("int_arg", value),
                ),
                emit     = emit,
                context  = context
            )
        else:
            value_name = context.allocateTempName("int_value")

            makeExpressionCode(
                to_name    = value_name,
                expression = value
            )

            base_name = context.allocateTempName("int_base")

            makeExpressionCode(
                to_name    = base_name,
                expression = base
            )

            Generator.getBuiltinInt2Code(
                to_name    = to_name,
                base_name  = base_name,
                value_name = value_name,
                emit       = emit,
                context    = context
            )
    elif Utils.python_version < 300 and expression.isExpressionBuiltinLong():
        value = expression.getValue()
        base = expression.getBase()

        assert value is not None

        if base is None:
            generateCAPIObjectCode(
                to_name  = to_name,
                capi     = "PyNumber_Long",
                arg_desc = (
                    ("long_arg", value),
                ),
                emit     = emit,
                context  = context
            )
        else:
            value_name = context.allocateTempName("long_value")

            makeExpressionCode(
                to_name    = value_name,
                expression = value
            )

            base_name = context.allocateTempName("int_base")

            makeExpressionCode(
                to_name    = base_name,
                expression = base
            )

            Generator.getBuiltinLong2Code(
                to_name    = to_name,
                base_name  = base_name,
                value_name = value_name,
                emit       = emit,
                context    = context
            )
    elif expression.isExpressionImportName():
        from_arg_name = context.allocateTempName("import_name_from")

        makeExpressionCode(
            to_name    = from_arg_name,
            expression = expression.getModule()
        )

        Generator.getImportNameCode(
            to_name       = to_name,
            import_name   = expression.getImportName(),
            from_arg_name = from_arg_name,
            emit          = emit,
            context       = context
        )
    elif expression.isExpressionConditional():
        true_target = context.allocateLabel("condexpr_true")
        false_target = context.allocateLabel("condexpr_false")
        end_target = context.allocateLabel("condexpr_end")

        old_true_target = context.getTrueBranchTarget()
        old_false_target = context.getFalseBranchTarget()

        context.setTrueBranchTarget(true_target)
        context.setFalseBranchTarget(false_target)

        generateConditionCode(
            condition = expression.getCondition(),
            emit      = emit,
            context   = context
        )

        Generator.getLabelCode(true_target,emit)
        makeExpressionCode(
            to_name    = to_name,
            expression = expression.getExpressionYes()
        )
        needs_ref1 = context.needsCleanup(to_name)

        # Must not clean this up in other expression.
        if needs_ref1:
            context.removeCleanupTempName(to_name)

        real_emit = emit
        emit = Emission.SourceCodeCollector()

        makeExpressionCode(
            to_name    = to_name,
            expression = expression.getExpressionNo()
        )

        needs_ref2 = context.needsCleanup(to_name)

        # TODO: Need to buffer generated code, so we can emit extra reference if
        # not same.
        if needs_ref1 and not needs_ref2:
            Generator.getGotoCode(end_target, real_emit)
            Generator.getLabelCode(false_target, real_emit)

            real_emit.codes += emit.codes
            emit = real_emit

            emit("Py_INCREF( %s );" % to_name)
            context.addCleanupTempName(to_name)
        elif not needs_ref1 and needs_ref2:
            real_emit("Py_INCREF( %s );" % to_name)
            Generator.getGotoCode(end_target, real_emit)
            Generator.getLabelCode(false_target, real_emit)

            real_emit.codes += emit.codes
            emit = real_emit
        else:
            Generator.getGotoCode(end_target, real_emit)
            Generator.getLabelCode(false_target, real_emit)

            real_emit.codes += emit.codes
            emit = real_emit

        Generator.getLabelCode(end_target,emit)

        context.setTrueBranchTarget(old_true_target)
        context.setFalseBranchTarget(old_false_target)
    elif expression.isExpressionDictOperationGet():
        dict_name, key_name = generateExpressionsCode(
            expressions = (
                expression.getDict(),
                expression.getKey()
            ),
            names       = ("dget_dict", "dget_key"),
            emit        = emit,
            context     = context
        )

        Generator.getDictOperationGetCode(
            to_name   = to_name,
            dict_name = dict_name,
            key_name  = key_name,
            emit      = emit,
            context   = context
        )
    elif expression.isExpressionListOperationAppend():
        list_name, value_name = generateExpressionsCode(
            expressions = (
                expression.getList(),
                expression.getValue()
            ),
            names       = ("append_to", "append_value"),
            emit        = emit,
            context     = context
        )

        Generator.getListOperationAppendCode(
            to_name    = to_name,
            list_name  = list_name,
            value_name = value_name,
            emit       = emit,
            context    = context
        )
    elif expression.isExpressionSetOperationAdd():
        set_name, value_name = generateExpressionsCode(
            expressions = (
                expression.getSet(),
                expression.getValue()
            ),
            names       = ("setadd_to", "setadd_value"),
            emit        = emit,
            context     = context
        )

        Generator.getSetOperationAddCode(
            to_name    = to_name,
            set_name   = set_name,
            value_name = value_name,
            emit       = emit,
            context    = context
        )
    elif expression.isExpressionDictOperationSet():
        dict_name, key_name, value_name = generateExpressionsCode(
            expressions = (
                expression.getDict(),
                expression.getKey(),
                expression.getValue()
            ),
            names       = ("dictset_to", "dictset_key", "dictset_value"),
            emit        = emit,
            context     = context
        )

        Generator.getDictOperationSetCode(
            to_name    = to_name,
            dict_name  = dict_name,
            key_name   = key_name,
            value_name = value_name,
            emit       = emit,
            context    = context
        )
    elif expression.isExpressionSelectMetaclass():
        if expression.getMetaclass() is not None:
            metaclass_name = context.allocateTempName("class_meta")

            makeExpressionCode(
                to_name    = metaclass_name,
                expression = expression.getMetaclass()
            )
        else:
            metaclass_name = None

        bases_name = context.allocateTempName("class_bases")
        makeExpressionCode(
            to_name = bases_name,
            expression = expression.getBases()
        )

        Generator.getSelectMetaclassCode(
            to_name        = to_name,
            metaclass_name = metaclass_name,
            bases_name     = bases_name,
            emit           = emit,
            context        = context
        )
    elif expression.isExpressionBuiltinLocals():
        generateBuiltinLocalsCode(
            to_name     = to_name,
            locals_node = expression,
            emit        = emit,
            context     = context
        )
    elif expression.isExpressionBuiltinDir1():
        generateCAPIObjectCode(
            to_name  = to_name,
            capi     = "PyObject_Dir",
            arg_desc = (
                ("dir_arg", expression.getValue()),
            ),
            emit     = emit,
            context  = context
        )
    elif expression.isExpressionBuiltinVars():
        generateCAPIObjectCode(
            to_name  = to_name,
            capi     = "LOOKUP_VARS",
            arg_desc = (
                ("vars_arg", expression.getSource()),
            ),
            emit     = emit,
            context  = context
        )
    elif expression.isExpressionBuiltinOpen():
        generateCAPIObjectCode(
            to_name   = to_name,
            capi      = "BUILTIN_OPEN",
            arg_desc  = (
                ("open_filename", expression.getFilename()),
                ("open_mode", expression.getMode()),
                ("open_buffering", expression.getBuffering()),
            ),
            none_null = True,
            emit      = emit,
            context   = context
        )
    elif expression.isExpressionBuiltinRange1():
        generateCAPIObjectCode(
            to_name   = to_name,
            capi      = "BUILTIN_RANGE",
            arg_desc  = (
                ("range_arg", expression.getLow()),
            ),
            emit      = emit,
            context   = context
        )
    elif expression.isExpressionBuiltinRange2():
        generateCAPIObjectCode(
            to_name   = to_name,
            capi      = "BUILTIN_RANGE2",
            arg_desc  = (
                ("range2_low", expression.getLow()),
                ("range2_high", expression.getHigh()),
            ),
            emit      = emit,
            context   = context
        )
    elif expression.isExpressionBuiltinRange3():
        generateCAPIObjectCode(
            to_name   = to_name,
            capi      = "BUILTIN_RANGE3",
            arg_desc  = (
                ("range3_low", expression.getLow()),
                ("range3_high", expression.getHigh()),
                ("range3_step", expression.getStep()),
            ),
            emit      = emit,
            context   = context
        )
    elif expression.isExpressionBuiltinXrange():
        generateCAPIObjectCode(
            to_name   = to_name,
            capi      = "BUILTIN_XRANGE",
            arg_desc  = (
                ("xrange_low", expression.getLow()),
                ("xrange_high", expression.getHigh()),
                ("xrange_step", expression.getStep()),
            ),
            emit      = emit,
            none_null = True,
            context   = context
        )
    elif expression.isExpressionBuiltinFloat():
        generateCAPIObjectCode(
            to_name   = to_name,
            capi      = "TO_FLOAT",
            arg_desc  = (
                ("float_arg", expression.getValue()),
            ),
            emit      = emit,
            context   = context
        )
    elif expression.isExpressionBuiltinBool():
        generateCAPIObjectCode0(
            to_name   = to_name,
            capi      = "TO_BOOL",
            arg_desc  = (
                ("bool_arg", expression.getValue()),
            ),
            emit      = emit,
            context   = context
        )
    elif expression.isExpressionBuiltinChr():
        generateCAPIObjectCode(
            to_name   = to_name,
            capi      = "BUILTIN_CHR",
            arg_desc  = (
                ("chr_arg", expression.getValue()),
            ),
            emit      = emit,
            context   = context
        )
    elif expression.isExpressionBuiltinOrd():
        generateCAPIObjectCode(
            to_name   = to_name,
            capi      = "BUILTIN_ORD",
            arg_desc  = (
                ("ord_arg", expression.getValue()),
            ),
            emit      = emit,
            context   = context
        )
    elif expression.isExpressionBuiltinBin():
        generateCAPIObjectCode(
            to_name   = to_name,
            capi      = "BUILTIN_BIN",
            arg_desc  = (
                ("bin_arg", expression.getValue()),
            ),
            emit      = emit,
            context   = context
        )
    elif expression.isExpressionBuiltinOct():
        generateCAPIObjectCode(
            to_name   = to_name,
            capi      = "BUILTIN_OCT",
            arg_desc  = (
                ("oct_arg", expression.getValue()),
            ),
            emit      = emit,
            context   = context
        )
    elif expression.isExpressionBuiltinHex():
        generateCAPIObjectCode(
            to_name   = to_name,
            capi      = "BUILTIN_HEX",
            arg_desc  = (
                ("hex_arg", expression.getValue()),
            ),
            emit      = emit,
            context   = context
        )
    elif expression.isExpressionBuiltinLen():
        generateCAPIObjectCode(
            to_name   = to_name,
            capi      = "BUILTIN_LEN",
            arg_desc  = (
                ("len_arg", expression.getValue()),
            ),
            emit      = emit,
            context   = context
        )
    elif expression.isExpressionBuiltinTuple():
        generateCAPIObjectCode(
            to_name  = to_name,
            capi     = "PySequence_Tuple",
            arg_desc = (
                ("tuple_arg", expression.getValue()),
            ),
            emit     = emit,
            context  = context
        )
    elif expression.isExpressionBuiltinList():
        generateCAPIObjectCode(
            to_name  = to_name,
            capi     = "PySequence_List",
            arg_desc = (
                ("list_arg", expression.getValue()),
            ),
            emit     = emit,
            context  = context
        )
    elif expression.isExpressionBuiltinDict():
        if expression.getPositionalArgument():
            seq_name = context.allocateTempName("dict_seq")

            makeExpressionCode(
                to_name    = seq_name,
                expression = expression.getPositionalArgument(),
                allow_none = True
            )
        else:
            seq_name = None

        if expression.getNamedArgumentPairs():
            dict_name = context.allocateTempName("dict_arg")

            generateDictionaryCreationCode(
                to_name  = dict_name,
                pairs    = expression.getNamedArgumentPairs(),
                emit     = emit,
                context  = context
            )
        else:
            dict_name = None

        Generator.getBuiltinDict2Code(
            to_name   = to_name,
            seq_name  = seq_name,
            dict_name = dict_name,
            emit      = emit,
            context   = context
        )
    elif expression.isExpressionBuiltinSet():
        generateCAPIObjectCode(
            to_name  = to_name,
            capi     = "PySet_New",
            arg_desc = (
                ("set_arg", expression.getValue()),
            ),
            emit     = emit,
            context  = context
        )
    elif expression.isExpressionBuiltinType3():
        type_name = context.allocateTempName("type_name")
        bases_name = context.allocateTempName("type_bases")
        dict_name = context.allocateTempName("type_dict")

        makeExpressionCode(
            to_name    = type_name,
            expression = expression.getTypeName()
        )
        makeExpressionCode(
            to_name    = bases_name,
            expression = expression.getBases()
        )
        makeExpressionCode(
            to_name    = dict_name,
            expression = expression.getDict()
        )

        Generator.getBuiltinType3Code(
            to_name = to_name,
            type_name = type_name,
            bases_name = bases_name,
            dict_name  = dict_name,
            emit     = emit,
            context  = context
        )
    elif expression.isExpressionBuiltinSuper():
        type_name, object_name = generateExpressionsCode(
            expressions = (
                expression.getType(), expression.getObject()
            ),
            names       = (
                "super_type", "super_object"
            ),
            emit        = emit,
            context     = context
        )

        Generator.getBuiltinSuperCode(
            to_name     = to_name,
            type_name   = type_name,
            object_name = object_name,
            emit        = emit,
            context     = context
        )
    elif expression.isExpressionYield():
        value_name = context.allocateTempName("yield")

        makeExpressionCode(
            to_name    = value_name,
            expression = expression.getExpression()
        )

        Generator.getYieldCode(
            to_name    = to_name,
            value_name = value_name,
            in_handler = expression.isExceptionPreserving(),
            emit       = emit,
            context    = context
        )
    elif expression.isExpressionYieldFrom():
        value_name = context.allocateTempName("yield_from")

        makeExpressionCode(
            to_name    = value_name,
            expression = expression.getExpression()
        )

        Generator.getYieldFromCode(
            to_name    = to_name,
            value_name = value_name,
            in_handler = expression.isExceptionPreserving(),
            emit       = emit,
            context    = context
        )
    elif expression.isExpressionSideEffects():
        for side_effect in expression.getSideEffects():
            generateStatementOnlyCode(
                value   = side_effect,
                emit    = emit,
                context = context
            )

        makeExpressionCode(
            to_name    = to_name,
            expression = expression.getExpression()
        )
    elif expression.isExpressionBuiltinEval():
        generateEvalCode(
            to_name   = to_name,
            eval_node = expression,
            emit      = emit,
            context   = context
        )
    elif Utils.python_version < 300 and \
         expression.isExpressionBuiltinExecfile():
        generateExecfileCode(
            to_name       = to_name,
            execfile_node = expression,
            emit          = emit,
            context       = context
        )
    elif Utils.python_version >= 300 and \
         expression.isExpressionBuiltinExec():
        # exec builtin of Python3, as opposed to Python2 statement
        generateEvalCode(
            to_name   = to_name,
            eval_node = expression,
            emit      = emit,
            context   = context
        )
    elif expression.isExpressionBuiltinCompile():
        source_name = context.allocateTempName("compile_source")
        filename_name = context.allocateTempName("compile_filename")
        mode_name = context.allocateTempName("compile_mode")

        makeExpressionCode(
            to_name    = source_name,
            expression = expression.getSourceCode()
        )
        makeExpressionCode(
            to_name    = filename_name,
            expression = expression.getFilename()
        )
        makeExpressionCode(
            to_name    = mode_name,
            expression = expression.getMode()
        )

        if expression.getFlags() is not None:
            flags_name = context.allocateTempName("compile_flags")

            makeExpressionCode(
                to_name    = flags_name,
                expression = expression.getFlags(),
            )
        else:
            flags_name = "NULL"

        if expression.getDontInherit() is not None:
            dont_inherit_name = context.allocateTempName("compile_dont_inherit")

            makeExpressionCode(
                to_name    = dont_inherit_name,
                expression = expression.getDontInherit()
            )
        else:
            dont_inherit_name = "NULL"

        if expression.getOptimize() is not None:
            optimize_name = context.allocateTempName("compile_dont_inherit")

            makeExpressionCode(
                to_name    = optimize_name,
                expression = expression.getOptimize()
            )
        else:
            optimize_name = "NULL"

        Generator.getCompileCode(
            to_name           = to_name,
            source_name       = source_name,
            filename_name     = filename_name,
            mode_name         = mode_name,
            flags_name        = flags_name,
            dont_inherit_name = dont_inherit_name,
            optimize_name     = optimize_name,
            emit              = emit,
            context           = context
        )
    elif expression.isExpressionTryFinally():
        generateTryFinallyCode(
            to_name   = to_name,
            statement = expression,
            emit      = emit,
            context   = context
        )
    elif expression.isExpressionRaiseException():
        # Missed optimization opportunity, please report.
        if Options.isDebug():
            parent = expression.parent
            assert parent.isExpressionSideEffects() or \
                   parent.isExpressionConditional(), \
                   ( expression, expression.parent )

        raise_type_name  = context.allocateTempName("raise_type")

        generateExpressionCode(
            to_name     = raise_type_name,
            expression  = expression.getExceptionType(),
            emit        = emit,
            context     = context
        )

        raise_value_name  = context.allocateTempName("raise_value")

        generateExpressionCode(
            to_name     = raise_value_name,
            expression  = expression.getExceptionValue(),
            emit        = emit,
            context     = context
        )

        emit("%s = NULL;" % to_name)

        Generator.getRaiseExceptionWithValueCode(
            raise_type_name  = raise_type_name,
            raise_value_name = raise_value_name,
            implicit         = True,
            emit             = emit,
            context          = context
        )
    else:
        assert False, expression

    context.setSourceReference(None)


def generateExpressionsCode(names, expressions, emit, context):
    assert len(names) == len(expressions)

    result = []
    for name, expression in zip(names, expressions):
        if expression is not None:
            to_name = context.allocateTempName(name)

            generateExpressionCode(
                to_name    = to_name,
                expression = expression,
                emit       = emit,
                context    = context
            )
        else:
            to_name = None

        result.append(to_name)

    return result


def generateExpressionCode(to_name, expression, emit, context,
                            allow_none = False):
    try:
        _generateExpressionCode(
            to_name    = to_name,
            expression = expression,
            emit       = emit,
            context    = context,
            allow_none = allow_none
        )
    except:
        Tracing.printError(
            "Problem with %r at %s" % (
                expression,
                "" if expression is None else expression.getSourceReference()
            )
        )
        raise


def generateAssignmentAttributeCode(lookup_source, attribute_name,
                                    value, emit, context):

    value_name = context.allocateTempName("assattr_name")
    generateExpressionCode(
        to_name    = value_name,
        expression = value,
        emit       = emit,
        context    = context
    )

    target_name = context.allocateTempName("assattr_target")
    generateExpressionCode(
        to_name    = target_name,
        expression = lookup_source,
        emit       = emit,
        context    = context
    )

    if attribute_name == "__dict__":
        Generator.getAttributeAssignmentDictSlotCode(
            target_name = target_name,
            value_name  = value_name,
            emit        = emit,
            context     = context
        )
    elif attribute_name == "__class__":
        Generator.getAttributeAssignmentClassSlotCode(
            target_name = target_name,
            value_name  = value_name,
            emit        = emit,
            context     = context
        )
    else:
        Generator.getAttributeAssignmentCode(
            target_name    = target_name,
            value_name     = value_name,
            attribute_name = Generator.getConstantCode(
                context  = context,
                constant = attribute_name
            ),
            emit           = emit,
            context        = context
        )


def generateAssignmentSubscriptCode(subscribed, subscript, value, emit,
                                    context):
    integer_subscript = False
    if subscript.isExpressionConstantRef():
        constant = subscript.getConstant()

        if Constants.isIndexConstant(constant):
            constant_value = int(constant)

            if abs(constant_value) < 2**31:
                integer_subscript = True

    value_name = context.allocateTempName("ass_subvalue")

    generateExpressionCode(
        to_name    = value_name,
        expression = value,
        emit       = emit,
        context    = context
    )

    subscribed_name = context.allocateTempName("ass_subscribed")
    generateExpressionCode(
        to_name    = subscribed_name,
        expression = subscribed,
        emit       = emit,
        context    = context
    )


    subscript_name = context.allocateTempName("ass_subscript")

    generateExpressionCode(
        to_name    = subscript_name,
        expression = subscript,
        emit       = emit,
        context    = context
    )

    if integer_subscript:
        Generator.getIntegerSubscriptAssignmentCode(
            subscribed_name = subscribed_name,
            subscript_name  = subscript_name,
            subscript_value = constant_value,
            value_name      = value_name,
            emit            = emit,
            context         = context
        )
    else:
        Generator.getSubscriptAssignmentCode(
            target_name     = subscribed_name,
            subscript_name  = subscript_name,
            value_name      = value_name,
            emit            = emit,
            context         = context
        )


def generateAssignmentSliceCode(lookup_source, lower, upper, value,
                                emit, context):
    value_name = context.allocateTempName("sliceass_value")

    generateExpressionCode(
        to_name    = value_name,
        expression = value,
        emit       = emit,
        context    = context
    )

    if decideSlicing(lower, upper):
        target_name = context.allocateTempName("sliceass_target")

        generateExpressionCode(
            to_name    = target_name,
            expression = lookup_source,
            emit       = emit,
            context    = context
        )

        lower_name, upper_name = generateSliceRangeIdentifier(
            lower   = lower,
            upper   = upper,
            scope   = "sliceass",
            emit    = emit,
            context = context
        )

        return Generator.getSliceAssignmentIndexesCode(
            target_name = target_name,
            lower_name  = lower_name,
            upper_name  = upper_name,
            value_name  = value_name,
            emit        = emit,
            context     = context
        )
    else:
        target_name, lower_name, upper_name = generateExpressionsCode(
            names       = (
                "sliceass_target", "sliceass_lower", "sliceass_upper"
            ),
            expressions = (
                lookup_source,
                lower,
                upper
            ),
            emit        = emit,
            context     = context
        )

        if _slicing_available:
            Generator.getSliceAssignmentCode(
                target_name = target_name,
                upper_name  = upper_name,
                lower_name  = lower_name,
                value_name  = value_name,
                emit        = emit,
                context     = context
            )
        else:
            subscript_name = context.allocateTempName("sliceass_subscript")

            # TODO: The decision should be done during optimization, so
            # _slicing_available should play no role at all.
            Generator.getSliceObjectCode(
                to_name    = subscript_name,
                lower_name = lower_name,
                upper_name = upper_name,
                step_name  = None,
                emit       = emit,
                context    = context
            )

            Generator.getSubscriptAssignmentCode(
                target_name    = target_name,
                subscript_name = subscript_name,
                value_name     = value_name,
                emit           = emit,
                context        = context
            )


def generateDelSubscriptCode(subscribed, subscript, emit, context):
    target_name, subscript_name = generateExpressionsCode(
        expressions = (subscribed, subscript),
        names       = ("delsubscr_target", "delsubscr_subscript"),
        emit        = emit,
        context     = context
    )

    Generator.getSubscriptDelCode(
        target_name    = target_name,
        subscript_name = subscript_name,
        emit           = emit,
        context        = context
    )


def generateDelSliceCode(target, lower, upper, emit, context):
    if decideSlicing( lower, upper ):
        target_name = context.allocateTempName("slicedel_target")

        generateExpressionCode(
            to_name    = target_name,
            expression = target,
            emit       = emit,
            context    = context
        )

        lower_name, upper_name = generateSliceRangeIdentifier(
            lower   = lower,
            upper   = upper,
            scope   = "slicedel",
            emit    = emit,
            context = context
        )

        Generator.getSliceDelCode(
            target_name = target_name,
            lower_name  = lower_name,
            upper_name  = upper_name,
            emit        = emit,
            context     = context
        )
    else:
        subscript_name = context.allocateTempName("sliceass_subscript")

        target_name, lower_name, upper_name = generateExpressionsCode(
            names       = (
                "slicedel_target", "slicedel_lower", "slicedel_upper"
            ),
            expressions = (
                target,
                lower,
                upper
            ),
            emit        = emit,
            context     = context
        )

        Generator.getSliceObjectCode(
            to_name    = subscript_name,
            lower_name = lower_name,
            upper_name = upper_name,
            step_name  = None,
            emit       = emit,
            context    = context
        )

        Generator.getSubscriptDelCode(
            target_name    = target_name,
            subscript_name = subscript_name,
            emit           = emit,
            context        = context
        )

def generateDelAttributeCode(statement, emit, context):
    target_name = context.allocateTempName("attrdel_target")

    generateExpressionCode(
        to_name    = target_name,
        expression = statement.getLookupSource(),
        emit       = emit,
        context    = context
    )

    Generator.getAttributeDelCode(
        target_name    = target_name,
        attribute_name = Generator.getConstantCode(
            context  = context,
            constant = statement.getAttributeName()
        ),
        emit           = emit,
        context        = context
    )


def _generateEvalCode(to_name, node, emit, context):
    source_name = context.allocateTempName("eval_source")
    globals_name = context.allocateTempName("eval_globals")
    locals_name = context.allocateTempName("eval_locals")

    generateExpressionCode(
        to_name    = source_name,
        expression = node.getSourceCode(),
        emit       = emit,
        context    = context
    )

    generateExpressionCode(
        to_name    = globals_name,
        expression = node.getGlobals(),
        emit       = emit,
        context    = context
    )

    generateExpressionCode(
        to_name    = locals_name,
        expression = node.getLocals(),
        emit       = emit,
        context    = context
    )

    if node.isExpressionBuiltinEval() or \
         (Utils.python_version >= 300 and node.isExpressionBuiltinExec()):
        filename = "<string>"
    else:
        filename = "<execfile>"

    Generator.getEvalCode(
        to_name       = to_name,
        source_name   = source_name,
        globals_name  = globals_name,
        locals_name   = locals_name,
        filename_name = Generator.getConstantCode(
            constant = filename,
            context  = context
        ),
        mode_name     = Generator.getConstantCode(
            constant = "eval" if node.isExpressionBuiltinEval() else "exec",
            context  = context
        ),
        emit          = emit,
        context       = context
    )

def generateEvalCode(to_name, eval_node, emit, context):
    return _generateEvalCode(
        to_name = to_name,
        node    = eval_node,
        emit    = emit,
        context = context
    )

def generateExecfileCode(to_name, execfile_node, emit, context):
    return _generateEvalCode(
        to_name = to_name,
        node    = execfile_node,
        emit    = emit,
        context = context
    )

def generateExecCode(exec_def, emit, context):
    source_name = context.allocateTempName("eval_source")
    globals_name = context.allocateTempName("eval_globals")
    locals_name = context.allocateTempName("eval_locals")

    generateExpressionCode(
        to_name    = source_name,
        expression = exec_def.getSourceCode(),
        emit       = emit,
        context    = context
    )

    generateExpressionCode(
        to_name    = globals_name,
        expression = exec_def.getGlobals(),
        emit       = emit,
        context    = context
    )

    generateExpressionCode(
        to_name    = locals_name,
        expression = exec_def.getLocals(),
        emit       = emit,
        context    = context
    )

    source_ref = exec_def.getSourceReference()

    # Filename with origin in improved mode.
    if Options.isFullCompat():
        filename_name = Generator.getConstantCode(
            constant = "<string>",
            context  = context
        )
    else:
        filename_name = Generator.getConstantCode(
            constant = "<string at %s>" % source_ref.getAsString(),
            context  = context
        )

    provider = exec_def.getParentVariableProvider()
    store_back = provider.isExpressionFunctionBody() and \
                 provider.isUnqualifiedExec()

    Generator.getExecCode(
        source_name   = source_name,
        globals_name  = globals_name,
        locals_name   = locals_name,
        filename_name = filename_name,
        store_back    = store_back,
        provider      = provider,
        emit          = emit,
        context       = context,
    )


def generateTryNextExceptStopIterationCode(statement, emit, context):
    if statement.public_exc:
        return False

    handling = statement.getExceptionHandling()

    if handling is None:
        return False

    tried_statements = statement.getBlockTry().getStatements()

    if len(tried_statements) != 1:
        return False

    handling_statements = handling.getStatements()

    if len(handling_statements) != 1:
        return False

    tried_statement = tried_statements[0]

    if not tried_statement.isStatementAssignmentVariable():
        return False

    assign_source = tried_statement.getAssignSource()

    if not assign_source.isExpressionBuiltinNext1():
        return False

    handling_statement = handling_statements[0]

    if not handling_statement.isStatementConditional():
        return False

    yes_statements = handling_statement.getBranchYes().getStatements()
    no_statements = handling_statement.getBranchNo().getStatements()

    if len(yes_statements) != 1:
        return False

    if not yes_statements[0].isStatementBreakLoop():
        return False

    if len(no_statements) != 1:
        return False

    if not no_statements[0].isStatementReraiseException() or \
       not no_statements[0].isStatementReraiseException():
        return False

    tmp_name = context.allocateTempName("next_source")

    generateExpressionCode(
        expression = assign_source.getValue(),
        to_name    = tmp_name,
        emit       = emit,
        context    = context
    )

    tmp_name2 = context.allocateTempName("assign_source")

    Generator.getBuiltinLoopBreakNextCode(
        to_name = tmp_name2,
        value   = tmp_name,
        emit    = emit,
        context = context
    )

    Generator.getVariableAssignmentCode(
        tmp_name = tmp_name2,
        variable = tried_statement.getTargetVariableRef().getVariable(),
        emit     = emit,
        context  = context
    )

    if context.needsCleanup(tmp_name2):
        context.removeCleanupTempName(tmp_name2)

    return True


def generateTryExceptCode(statement, emit, context):
    if generateTryNextExceptStopIterationCode(statement, emit, context):
        return

    tried_block = statement.getBlockTry()
    handling_block = statement.getExceptionHandling()

    # Optimization should not leave it present otherwise, something that cannot
    # raise, must already be reduced.
    assert tried_block.mayRaiseException(BaseException)

    old_ok = context.getExceptionNotOccured()

    no_exception = context.allocateLabel("try_except_end")
    context.setExceptionNotOccured(no_exception)

    old_escape = context.getExceptionEscape()
    context.setExceptionEscape(context.allocateLabel("try_except_handler"))

    emit("// Tried block of try/except")

    _generateStatementSequenceCode(
        statement_sequence = tried_block,
        emit               = emit,
        context            = context,
    )

    Generator.pushLineNumberBranch()

    Generator.getGotoCode(context.getExceptionNotOccured(), emit)
    Generator.getLabelCode(context.getExceptionEscape(),emit)

    # Inside the exception handler, we need to error exit to the outside
    # handler.
    context.setExceptionEscape(old_escape)
    context.setExceptionNotOccured(old_ok)

    old_published = context.isExceptionPublished()
    context.setExceptionPublished(statement.needsExceptionPublish())

    emit("// Exception handler of try/except")
    _generateStatementSequenceCode(
        statement_sequence = handling_block,
        context            = context,
        emit               = emit,
        allow_none         = True
    )

    if handling_block is not None and handling_block.isStatementAborting():
        Generator.getExceptionUnpublishedReleaseCode(
            emit       = emit,
            context    = context
        )

    # TODO: May have to do this for before return, break, and continue as well.
    if not statement.needsExceptionPublish():
        emit(
             """\
Py_DECREF( exception_type );
Py_XDECREF( exception_value );
Py_XDECREF( exception_tb );
"""
        )

    Generator.getLabelCode(no_exception,emit)

    context.setExceptionPublished(old_published)

    Generator.popLineNumberBranch()

_temp_whitelist = []

def generateTryFinallyCode(to_name, statement, emit, context):
    # The try/finally is very hard for C-ish code generation. We need to react
    # on break, continue, return, raise in the tried blocks with reraise. We
    # need to publish it to the handler (Python3) or save it for re-raise,
    # unless another exception or continue, break, return occurs.

    # First, this may be used as an expression, in which case to_name won't be
    # set, we ask the checks to ignore currently set values.
    global _temp_whitelist

    if to_name is not None:
        _temp_whitelist = context.getCleanupTempnames()

    tried_block = statement.getBlockTry()
    final_block = statement.getBlockFinal()

    # The tried statements might raise, for which we define an escape. As we
    # only want to have the final block one, we use this as the target for the
    # others, but make them set flags.
    old_escape = context.getExceptionEscape()
    tried_handler_escape = context.allocateLabel("try_finally_handler")
    context.setExceptionEscape(tried_handler_escape)

    # This is the handler start label, that is where we jump to.
    if statement.needsContinueHandling() or \
       statement.needsBreakHandling() or \
       statement.needsReturnHandling():
        handler_start_target = context.allocateLabel(
            "try_finally_handler_start"
        )
    else:
        handler_start_target = None

    # Set the indicator for "continue" and "break" first. Mostly for ease of
    # use, the C++ compiler can push it back as it sees fit. When an actual
    # continue or break occurs, they will set the indicators. We indicate
    # the name to use for that in the targets.
    if statement.needsContinueHandling():
        continue_name = context.allocateTempName("continue", "bool")

        emit("%s = false;" % continue_name)

        old_continue_target = context.getLoopContinueTarget()
        context.setLoopContinueTarget(
            handler_start_target,
            continue_name
        )

    # See above.
    if statement.needsBreakHandling():
        break_name = context.allocateTempName("break", "bool")

        emit("%s = false;" % break_name)

        old_break_target = context.getLoopBreakTarget()
        context.setLoopBreakTarget(
            handler_start_target,
            break_name
        )

    # For return, we need to catch that too.
    if statement.needsReturnHandling():
        old_return = context.getReturnTarget()
        context.setReturnTarget(handler_start_target)

    # Initialise expression, so even if it exits, the compiler will not see a
    # random value there. This shouldn't be necessary and hopefully the C++
    # compiler will find out. Since these are rare, it doesn't matter.
    if to_name is not None:
        # TODO: Silences the compiler for now. If we are honest, a real
        # Py_XDECREF would be needed at release time then.
        emit("%s = NULL;" % to_name)

    # Now the tried block can be generated.
    emit("// Tried code")
    _generateStatementSequenceCode(
        statement_sequence = tried_block,
        emit               = emit,
        context            = context
    )

    # An eventual assignment of the tried expression if any is practically part
    # of the tried block, just last.
    if to_name is not None:
        generateExpressionCode(
            to_name    = to_name,
            expression = statement.getExpression(),
            emit       = emit,
            context    = context
        )

    # So this is when we completed the handler without exiting.
    if statement.needsReturnHandling() and Utils.python_version >= 330:
        emit(
            "tmp_return_value = NULL;"
        )

    if handler_start_target is not None:
        Generator.getLabelCode(handler_start_target,emit)


    # For the try/finally expression, we allow that the tried block may in fact
    # not raise, continue, or break at all, but it would merely be there to do
    # something before an expression. Kind of as a side effect. To address that
    # we need to check.
    tried_block_may_raise = tried_block.mayRaiseException(BaseException)
    # TODO: This should be true, but it isn't.
    # assert tried_block_may_raise or to_name is not None

    if tried_block_may_raise:
        emit("// Final block of try/finally")

        # The try/finally of Python3 might publish an exception to the handler,
        # which makes things more complex.
        if not statement.needsExceptionPublish():
            keeper_type, keeper_value, keeper_tb = \
                context.getExceptionKeeperVariables()

            emit(
                Generator.CodeTemplates.template_final_handler_start % {
                    "final_error_target" : context.getExceptionEscape(),
                    "keeper_type"        : keeper_type,
                    "keeper_value"       : keeper_value,
                    "keeper_tb"          : keeper_tb
                }
            )
        else:
            emit(
                Generator.CodeTemplates.template_final_handler_start_python3 % {
                    "final_error_target" : context.getExceptionEscape(),
                }
            )

    # Restore the handlers changed during the tried block. For the final block
    # we may set up others later.
    context.setExceptionEscape(old_escape)
    if statement.needsContinueHandling():
        context.setLoopContinueTarget(old_continue_target)
    if statement.needsBreakHandling():
        context.setLoopBreakTarget(old_break_target)
    if statement.needsReturnHandling():
        context.setReturnTarget(old_return)
    old_return_value_release = context.getReturnReleaseMode()
    context.setReturnReleaseMode(statement.needsReturnValueRelease())

    # If the final block might raise, we need to catch that, so we release a
    # preserved exception and don't leak it.
    final_block_may_raise = \
      final_block is not None and \
      final_block.mayRaiseException(BaseException) and \
      not statement.needsExceptionPublish()

    final_block_may_return = \
      final_block is not None and \
      final_block.mayReturn()

    final_block_may_break = \
      final_block is not None and \
      final_block.mayBreak()

    final_block_may_continue = \
      final_block is not None and \
      final_block.mayContinue()

    # That would be a SyntaxError
    assert not final_block_may_continue

    old_return = context.getReturnTarget()
    old_break_target = context.getLoopBreakTarget()
    old_continue_target = context.getLoopContinueTarget()

    if final_block is not None:
        if Utils.python_version < 300 or True:
            tried_lineno_name = context.allocateTempName("tried_lineno", "int")
            Generator.getLineNumberCode(tried_lineno_name, emit, context)

        if final_block_may_raise:
            old_escape = context.getExceptionEscape()
            context.setExceptionEscape(
                context.allocateLabel("try_finally_handler_error")
            )

        if final_block_may_return:
            context.setReturnTarget(
                context.allocateLabel("try_finally_handler_return")
            )

        if final_block_may_break:
            context.setLoopBreakTarget(
                context.allocateLabel("try_finally_handler_break")
            )

        _generateStatementSequenceCode(
            statement_sequence = final_block,
            emit               = emit,
            context            = context
        )

        if Utils.python_version < 300 or True:
            Generator.getSetLineNumberCodeRaw(tried_lineno_name, emit, context)
    else:
        # Final block is only optional for try/finally expressions. For
        # statements, they should be optimized way.
        assert to_name is not None

    context.setReturnReleaseMode(old_return_value_release)

    emit("// Re-reraise as necessary after finally was executed.")

    if tried_block_may_raise and not statement.needsExceptionPublish():
        emit(
            Generator.CodeTemplates.template_final_handler_reraise % {
                "exception_exit" : old_escape,
                "keeper_type"    : keeper_type,
                "keeper_value"   : keeper_value,
                "keeper_tb"      : keeper_tb
            }
        )

    if Utils.python_version >= 330:
        return_template = Generator.CodeTemplates.\
          template_final_handler_return_reraise
    else:
        provider = statement.getParentVariableProvider()

        if not provider.isExpressionFunctionBody() or \
           not provider.isGenerator():
            return_template = Generator.CodeTemplates.\
              template_final_handler_return_reraise
        else:
            return_template = Generator.CodeTemplates.\
              template_final_handler_generator_return_reraise

    if statement.needsReturnHandling():
        emit(
            return_template % {
                "parent_return_target" : old_return
            }
        )

    if statement.needsContinueHandling():
        emit(
            """\
// Continue if entered via continue.
if ( %(continue_name)s )
{
""" % {
                "continue_name" : continue_name
            }
        )

        if type(old_continue_target) is tuple:
            emit("%s = true;" % old_continue_target[1])
            Generator.getGotoCode(old_continue_target[0], emit)
        else:
            Generator.getGotoCode(old_continue_target, emit)

        emit("}")
    if statement.needsBreakHandling():
        emit(
            """\
// Break if entered via break.
if ( %(break_name)s )
{
""" % {
                "break_name" : break_name
            }
        )

        if type(old_break_target) is tuple:
            emit("%s = true;" % old_break_target[1])
            Generator.getGotoCode(old_break_target[0], emit)
        else:
            Generator.getGotoCode(old_break_target, emit)

        emit("}")

    final_end_target = context.allocateLabel("finally_end")
    Generator.getGotoCode(final_end_target, emit)

    if final_block_may_raise:
        Generator.getLabelCode(context.getExceptionEscape(),emit)

        # TODO: Avoid the labels in this case
        if tried_block_may_raise:
            if Utils.python_version < 300:
                emit(
                    """\
Py_XDECREF( %(keeper_type)s );%(keeper_type)s = NULL;
Py_XDECREF( %(keeper_value)s );%(keeper_value)s = NULL;
Py_XDECREF( %(keeper_tb)s );%(keeper_tb)s = NULL;""" % {
                        "keeper_type"  : keeper_type,
                        "keeper_value" : keeper_value,
                        "keeper_tb"    : keeper_tb
                    }
                )
            else:
                emit("""\
if ( %(keeper_type)s )
{
    NORMALIZE_EXCEPTION( &%(keeper_type)s, &%(keeper_value)s, &%(keeper_tb)s );
    PyException_SetContext( %(keeper_value)s, exception_value );
    Py_DECREF( exception_type );
    exception_type = %(keeper_type)s;
    // Py_XDECREF( exception_value );
    exception_value = %(keeper_value)s;
    Py_XDECREF( exception_tb );
    exception_tb = %(keeper_tb)s;


}
""" % {
                        "keeper_type"  : keeper_type,
                        "keeper_value" : keeper_value,
                        "keeper_tb"    : keeper_tb
                    }
                )


        context.setExceptionEscape(old_escape)
        Generator.getGotoCode(context.getExceptionEscape(), emit)

    if final_block_may_return:
        Generator.getLabelCode(context.getReturnTarget(),emit)

        # TODO: Avoid the labels in this case
        if tried_block_may_raise and not statement.needsExceptionPublish():
            emit(
                """\
Py_XDECREF( %(keeper_type)s );%(keeper_type)s = NULL;
Py_XDECREF( %(keeper_value)s );%(keeper_value)s = NULL;
Py_XDECREF( %(keeper_tb)s );%(keeper_tb)s = NULL;""" % {
                "keeper_type"  : keeper_type,
                "keeper_value" : keeper_value,
                "keeper_tb"    : keeper_tb
            }
        )

        context.setReturnTarget(old_return)
        Generator.getGotoCode(context.getReturnTarget(), emit)

    if final_block_may_break:
        Generator.getLabelCode(context.getLoopBreakTarget(),emit)

        # TODO: Avoid the labels in this case
        if tried_block_may_raise and not statement.needsExceptionPublish():
            emit(
            """\
Py_XDECREF( %(keeper_type)s );%(keeper_type)s = NULL;
Py_XDECREF( %(keeper_value)s );%(keeper_value)s = NULL;
Py_XDECREF( %(keeper_tb)s );%(keeper_tb)s = NULL;""" % {
                "keeper_type"  : keeper_type,
                "keeper_value" : keeper_value,
                "keeper_tb"    : keeper_tb
            }
        )

        context.setLoopBreakTarget(old_break_target)
        Generator.getGotoCode(context.getLoopBreakTarget(),emit)

    Generator.getLabelCode(final_end_target,emit)

    # Restore whitelist to previous state.
    if to_name is not None:
        _temp_whitelist = []


def generateRaiseCode(statement, emit, context):
    exception_type  = statement.getExceptionType()
    exception_value = statement.getExceptionValue()
    exception_tb    = statement.getExceptionTrace()
    exception_cause = statement.getExceptionCause()

    context.markAsNeedsExceptionVariables()

    # Exception cause is only possible with simple raise form.
    if exception_cause is not None:
        assert exception_type is not None
        assert exception_value is None
        assert exception_tb is None

        raise_type_name  = context.allocateTempName("raise_type")

        generateExpressionCode(
            to_name     = raise_type_name,
            expression  = exception_type,
            emit        = emit,
            context     = context
        )

        raise_cause_name  = context.allocateTempName("raise_type")

        generateExpressionCode(
            to_name     = raise_cause_name,
            expression  = exception_cause,
            emit        = emit,
            context     = context
        )

        Generator.getRaiseExceptionWithCauseCode(
            raise_type_name  = raise_type_name,
            raise_cause_name = raise_cause_name,
            emit             = emit,
            context          = context
        )
    elif exception_type is None:
        assert exception_cause is None
        assert exception_value is None
        assert exception_tb is None

        Generator.getReRaiseExceptionCode(
            emit    = emit,
            context = context
        )
    elif exception_value is None and exception_tb is None:
        raise_type_name  = context.allocateTempName("raise_type")

        generateExpressionCode(
            to_name     = raise_type_name,
            expression  = exception_type,
            emit        = emit,
            context     = context
        )

        Generator.getRaiseExceptionWithTypeCode(
            raise_type_name = raise_type_name,
            emit            = emit,
            context         = context
        )
    elif exception_tb is None:
        raise_type_name  = context.allocateTempName("raise_type")

        generateExpressionCode(
            to_name     = raise_type_name,
            expression  = exception_type,
            emit        = emit,
            context     = context
        )

        raise_value_name  = context.allocateTempName("raise_value")

        generateExpressionCode(
            to_name     = raise_value_name,
            expression  = exception_value,
            emit        = emit,
            context     = context
        )

        Generator.getRaiseExceptionWithValueCode(
            raise_type_name  = raise_type_name,
            raise_value_name = raise_value_name,
            implicit         = statement.isImplicit(),
            emit             = emit,
            context          = context
        )
    else:
        raise_type_name  = context.allocateTempName("raise_type")

        generateExpressionCode(
            to_name     = raise_type_name,
            expression  = exception_type,
            emit        = emit,
            context     = context
        )

        raise_value_name  = context.allocateTempName("raise_value")

        generateExpressionCode(
            to_name     = raise_value_name,
            expression  = exception_value,
            emit        = emit,
            context     = context
        )

        raise_tb_name = context.allocateTempName("raise_tb")

        generateExpressionCode(
            to_name     = raise_tb_name,
            expression  = exception_tb,
            emit        = emit,
            context     = context
        )

        Generator.getRaiseExceptionWithTracebackCode(
            raise_type_name  = raise_type_name,
            raise_value_name = raise_value_name,
            raise_tb_name    = raise_tb_name,
            emit             = emit,
            context          = context
        )


def generateUnpackCheckCode(statement, emit, context):
    iterator_name  = context.allocateTempName("iterator_name")

    generateExpressionCode(
        to_name     = iterator_name,
        expression  = statement.getIterator(),
        emit        = emit,
        context     = context
    )

    Generator.getUnpackCheckCode(
        iterator_name = iterator_name,
        count         = statement.getCount(),
        emit          = emit,
        context       = context,
    )

def generateImportModuleCode(to_name, expression, emit, context):
    provider = expression.getParentVariableProvider()

    globals_name = context.allocateTempName("import_globals")

    Generator.getLoadGlobalsCode(
        to_name = globals_name,
        emit    = emit,
        context = context
    )

    if provider.isPythonModule():
        locals_name = globals_name
    else:
        locals_name = context.allocateTempName("import_locals")

        Generator.getLoadLocalsCode(
            to_name  = locals_name,
            provider = expression.getParentVariableProvider(),
            mode     = "updated",
            emit     = emit,
            context  = context
        )

    Generator.getBuiltinImportCode(
        to_name          = to_name,
        module_name      = Generator.getConstantCode(
            constant = expression.getModuleName(),
            context  = context
        ),
        globals_name     = globals_name,
        locals_name      = locals_name,
        import_list_name = Generator.getConstantCode(
            constant = expression.getImportList(),
            context  = context
        ),
        level_name       = Generator.getConstantCode(
            constant = expression.getLevel(),
            context  = context
        ),
        emit             = emit,
        context          = context
    )

def generateBuiltinImportCode(to_name, expression, emit, context):
    module_name, globals_name, locals_name, import_list_name, level_name = \
      generateExpressionsCode(
        expressions = (
            expression.getImportName(),
            expression.getGlobals(),
            expression.getLocals(),
            expression.getFromList(),
            expression.getLevel()
        ),
        names       = (
            "import_modulename",
            "import_globals",
            "import_locals",
            "import_fromlist",
            "import_level"
        ),
        emit        = emit,
        context     = context
    )

    if expression.getGlobals() is None:
        globals_name = context.allocateTempName("import_globals")

        Generator.getLoadGlobalsCode(
            to_name = globals_name,
            emit    = emit,
            context = context
        )

    if expression.getLocals() is None:
        provider = expression.getParentVariableProvider()

        if provider.isPythonModule():
            locals_name = globals_name
        else:
            locals_name = context.allocateTempName("import_locals")

            Generator.getLoadLocalsCode(
                to_name  = locals_name,
                provider = provider,
                mode     = provider.getLocalsMode(),
                emit     = emit,
                context  = context
            )


    Generator.getBuiltinImportCode(
        to_name           = to_name,
        module_name       = module_name,
        globals_name      = globals_name,
        locals_name       = locals_name,
        import_list_name  = import_list_name,
        level_name        = level_name,
        emit              = emit,
        context           = context
    )


def generateImportStarCode(statement, emit, context):
    module_name = context.allocateTempName("star_imported")

    generateImportModuleCode(
        to_name    = module_name,
        expression = statement.getModule(),
        emit       = emit,
        context    = context
    )

    Generator.getImportFromStarCode(
        module_name = module_name,
        emit        = emit,
        context     = context
    )


def generateBranchCode(statement, emit, context):
    true_target = context.allocateLabel("branch_yes")
    false_target = context.allocateLabel("branch_no")
    end_target = context.allocateLabel("branch_end")

    old_true_target = context.getTrueBranchTarget()
    old_false_target = context.getFalseBranchTarget()

    context.setTrueBranchTarget(true_target)
    context.setFalseBranchTarget(false_target)

    generateConditionCode(
        condition = statement.getCondition(),
        emit      = emit,
        context   = context
    )

    context.setTrueBranchTarget(old_true_target)
    context.setFalseBranchTarget(old_false_target)

    Generator.getLabelCode(true_target, emit)

    Generator.pushLineNumberBranch()
    _generateStatementSequenceCode(
        statement_sequence = statement.getBranchYes(),
        emit               = emit,
        context            = context
    )
    Generator.popLineNumberBranch()

    if statement.getBranchNo() is not None:
        Generator.getGotoCode(end_target, emit)
        Generator.getLabelCode(false_target, emit)

        Generator.pushLineNumberBranch()
        _generateStatementSequenceCode(
            statement_sequence = statement.getBranchNo(),
            emit               = emit,
            context            = context
        )
        Generator.popLineNumberBranch()
        Generator.mergeLineNumberBranches()

        Generator.getLabelCode(end_target, emit)
    else:
        Generator.getLabelCode(false_target, emit)


def generateLoopCode(statement, emit, context):
    loop_start_label = context.allocateLabel("loop_start")
    if not statement.isStatementAborting():
        loop_end_label = context.allocateLabel("loop_end")
    else:
        loop_end_label = None

    Generator.getLabelCode(loop_start_label, emit)

    # The loop is re-entrant, therefore force setting the line number at start
    # again, even if the same as before.
    Generator.resetLineNumber()

    old_loop_break = context.getLoopBreakTarget()
    old_loop_continue = context.getLoopContinueTarget()

    context.setLoopBreakTarget(loop_end_label)
    context.setLoopContinueTarget(loop_start_label)

    _generateStatementSequenceCode(
        statement_sequence = statement.getLoopBody(),
        allow_none         = True,
        emit               = emit,
        context            = context
    )

    context.setLoopBreakTarget(old_loop_break)
    context.setLoopContinueTarget(old_loop_continue)

    Generator.getErrorExitBoolCode(
        condition = "CONSIDER_THREADING() == false",
        emit      = emit,
        context   = context
    )

    Generator.getGotoCode(loop_start_label, emit)

    if loop_end_label is not None:
        Generator.getLabelCode(loop_end_label, emit)



def generateReturnCode(statement, emit, context):
    return_value_name = context.getReturnValueName()

    if context.getReturnReleaseMode():
        emit("Py_DECREF( %s );" % return_value_name)

    generateExpressionCode(
        to_name    = return_value_name,
        expression = statement.getExpression(),
        emit       = emit,
        context    = context
    )

    if context.needsCleanup(return_value_name):
        context.removeCleanupTempName(return_value_name)
    else:
        emit(
            "Py_INCREF( %s );" % return_value_name
        )

    Generator.getGotoCode(context.getReturnTarget(), emit)


def generateGeneratorReturnCode(statement, emit, context):
    if Utils.python_version >= 330:
        return_value_name = context.getGeneratorReturnValueName()

        expression = statement.getExpression()

        if context.getReturnReleaseMode():
            emit("Py_DECREF( %s );" % return_value_name)

        generateExpressionCode(
            to_name    = return_value_name,
            expression = expression,
            emit       = emit,
            context    = context
        )

        if context.needsCleanup(return_value_name):
            context.removeCleanupTempName(return_value_name)
        else:
            emit(
                "Py_INCREF( %s );" % return_value_name
            )
    elif statement.getParentVariableProvider().needsGeneratorReturnHandling():
        return_value_name = context.getGeneratorReturnValueName()

        generator_return_name = context.allocateTempName(
            "generator_return",
            "bool",
            unique = True
        )

        emit("%s = false;" % generator_return_name)

    Generator.getGotoCode(context.getReturnTarget(), emit)


def generateAssignmentVariableCode(variable_ref, value, emit, context):
    tmp_name = context.allocateTempName("assign_source")

    generateExpressionCode(
        expression = value,
        to_name    = tmp_name,
        emit       = emit,
        context    = context
    )

    Generator.getVariableAssignmentCode(
        tmp_name = tmp_name,
        variable = variable_ref.getVariable(),
        emit     = emit,
        context  = context
    )

    if context.needsCleanup(tmp_name):
        context.removeCleanupTempName(tmp_name)


def generateStatementOnlyCode(value, emit, context):
    tmp_name = context.allocateTempName(
        base_name = "unused",
        type_code = "NUITKA_MAY_BE_UNUSED PyObject *",
        unique    = True
    )

    generateExpressionCode(
        expression = value,
        to_name    = tmp_name,
        emit       = emit,
        context    = context
    )

    Generator.getReleaseCode(
        release_name = tmp_name,
        emit         = emit,
        context      = context
    )


def generatePrintValueCode(destination, value, emit, context):
    if destination is not None:
        tmp_name_dest = context.allocateTempName("print_dest", unique = True)

        generateExpressionCode(
            expression = destination,
            to_name    = tmp_name_dest,
            emit       = emit,
            context    = context
        )
    else:
        tmp_name_dest = None

    tmp_name_printed = context.allocateTempName("print_value", unique = True)

    generateExpressionCode(
        expression = value,
        to_name    = tmp_name_printed,
        emit       = emit,
        context    = context
    )

    Generator.getPrintValueCode(
        dest_name  = tmp_name_dest,
        value_name = tmp_name_printed,
        emit       = emit,
        context    = context
    )


def generatePrintNewlineCode(destination, emit, context):
    if destination is not None:

        tmp_name_dest = context.allocateTempName("print_dest", unique = True)

        generateExpressionCode(
            expression = destination,
            to_name    = tmp_name_dest,
            emit       = emit,
            context    = context
        )
    else:
        tmp_name_dest = None

    Generator.getPrintNewlineCode(
        dest_name  = tmp_name_dest,
        emit       = emit,
        context    = context
    )


def _generateStatementCode(statement, emit, context):
    # This is a dispatching function with a branch per statement node type.
    # pylint: disable=R0912,R0915
    if not statement.isStatement():
        statement.dump()
        assert False

    if statement.isStatementAssignmentVariable():
        generateAssignmentVariableCode(
            variable_ref  = statement.getTargetVariableRef(),
            value         = statement.getAssignSource(),
            emit          = emit,
            context       = context
        )
    elif statement.isStatementAssignmentAttribute():
        generateAssignmentAttributeCode(
            lookup_source  = statement.getLookupSource(),
            attribute_name = statement.getAttributeName(),
            value          = statement.getAssignSource(),
            emit           = emit,
            context        = context
        )
    elif statement.isStatementAssignmentSubscript():
        generateAssignmentSubscriptCode(
            subscribed      = statement.getSubscribed(),
            subscript       = statement.getSubscript(),
            value           = statement.getAssignSource(),
            emit            = emit,
            context         = context
        )
    elif statement.isStatementAssignmentSlice():
        generateAssignmentSliceCode(
            lookup_source  = statement.getLookupSource(),
            lower          = statement.getLower(),
            upper          = statement.getUpper(),
            value          = statement.getAssignSource(),
            emit           = emit,
            context        = context
        )
    elif statement.isStatementDelVariable():
        Generator.getVariableDelCode(
            variable = statement.getTargetVariableRef().getVariable(),
            tolerant = statement.isTolerant(),
            emit     = emit,
            context  = context
        )
    elif statement.isStatementDelSubscript():
        generateDelSubscriptCode(
            subscribed = statement.getSubscribed(),
            subscript  = statement.getSubscript(),
            emit       = emit,
            context    = context
        )
    elif statement.isStatementDelSlice():
        generateDelSliceCode(
            target  = statement.getLookupSource(),
            lower   = statement.getLower(),
            upper   = statement.getUpper(),
            emit    = emit,
            context = context
        )
    elif statement.isStatementDelAttribute():
        generateDelAttributeCode(
            statement = statement,
            emit      = emit,
            context   = context
        )
    elif statement.isStatementExpressionOnly():
        generateStatementOnlyCode(
            value   = statement.getExpression(),
            emit    = emit,
            context = context
        )
    elif statement.isStatementReturn():
        generateReturnCode(
            statement = statement,
            emit      = emit,
            context   = context
        )
    elif statement.isStatementGeneratorReturn():
        generateGeneratorReturnCode(
            statement = statement,
            emit      = emit,
            context   = context
        )
    elif statement.isStatementConditional():
        generateBranchCode(
            statement = statement,
            emit      = emit,
            context   = context
        )
    elif statement.isStatementTryExcept():
        generateTryExceptCode(
            statement = statement,
            emit      = emit,
            context   = context
        )
    elif statement.isStatementTryFinally():
        generateTryFinallyCode(
            to_name   = None, # Not a try/finally expression.
            statement = statement,
            emit      = emit,
            context   = context
        )
    elif statement.isStatementPrintValue():
        generatePrintValueCode(
            destination = statement.getDestination(),
            value       = statement.getValue(),
            emit        = emit,
            context     = context
        )
    elif statement.isStatementPrintNewline():
        generatePrintNewlineCode(
            destination = statement.getDestination(),
            emit        = emit,
            context     = context
        )
    elif statement.isStatementImportStar():
        generateImportStarCode(
            statement = statement,
            emit      = emit,
            context   = context
        )
    elif statement.isStatementLoop():
        generateLoopCode(
            statement = statement,
            emit      = emit,
            context   = context
        )
    elif statement.isStatementBreakLoop():
        Generator.getLoopBreakCode(
            emit      = emit,
            context   = context
        )
    elif statement.isStatementContinueLoop():
        Generator.getLoopContinueCode(
            emit      = emit,
            context   = context
        )
    elif statement.isStatementRaiseException():
        generateRaiseCode(
            statement = statement,
            emit      = emit,
            context   = context
        )
    elif statement.isStatementSpecialUnpackCheck():
        generateUnpackCheckCode(
            statement = statement,
            emit      = emit,
            context   = context
        )
    elif statement.isStatementExec():
        generateExecCode(
            exec_def = statement,
            emit     = emit,
            context  = context
        )
    elif statement.isStatementDictOperationRemove():
        dict_name = context.allocateTempName("remove_dict", unique = True)
        key_name = context.allocateTempName("remove_key", unique = True)

        generateExpressionCode(
            to_name    = dict_name,
            expression = statement.getDict(),
            emit       = emit,
            context    = context
        )
        generateExpressionCode(
            to_name    = key_name,
            expression = statement.getKey(),
            emit       = emit,
            context    = context
        )

        Generator.getDictOperationRemoveCode(
            dict_name = dict_name,
            key_name  = key_name,
            emit      = emit,
            context   = context
        )
    elif statement.isStatementSetLocals():
        new_locals_name = context.allocateTempName("set_locals", unique = True)

        generateExpressionCode(
            to_name    = new_locals_name,
            expression = statement.getNewLocals(),
            emit       = emit,
            context    = context
        )

        Generator.getSetLocalsCode(
            new_locals_name = new_locals_name,
            emit            = emit,
            context         = context
        )
    elif statement.isStatementGeneratorEntry():
        emit(
            Generator.CodeTemplates.template_generator_initial_throw % {
                "frame_exception_exit" : context.getExceptionEscape()
            }
        )
    elif statement.isStatementPreserveFrameException():
        Generator.getFramePreserveExceptionCode(
            emit    = emit,
            context = context
        )
    elif statement.isStatementRestoreFrameException():
        Generator.getFrameRestoreExceptionCode(
            emit    = emit,
            context = context
        )
    elif statement.isStatementReraiseFrameException():
        Generator.getFrameReraiseExceptionCode(
            emit    = emit,
            context = context
        )
    elif statement.isStatementPublishException():
        context.markAsNeedsExceptionVariables()

        emit(
            Generator.CodeTemplates.template_publish_exception_to_handler % {
                "tb_making"        : Generator.getTracebackMakingIdentifier(
                    context = context
                ),
                "frame_identifier" : context.getFrameHandle()
            }
        )

        emit(
            "NORMALIZE_EXCEPTION( &exception_type, &exception_value, &exception_tb );"
        )
        if Utils.python_version >= 300:
            emit(
                """PyException_SetTraceback( exception_value, (PyObject *)exception_tb );"""
            )
        emit(
            "PUBLISH_EXCEPTION( &exception_type, &exception_value, &exception_tb );"
        )

    else:
        assert False, statement


def generateStatementCode(statement, emit, context):
    try:
        _generateStatementCode(statement, emit, context)

        try_finally_candidate = statement.parent.getParent()

        if try_finally_candidate is not None and \
           not try_finally_candidate.isExpression():
            # Complain if any temporary was not dealt with yet.
            assert not context.getCleanupTempnames() or \
                  context.getCleanupTempnames() == _temp_whitelist, \
              context.getCleanupTempnames()
    except Exception:
        Tracing.printError(
            "Problem with %r at %s" % (
                statement,
                statement.getSourceReference()
            )
        )
        raise


def _generateStatementSequenceCode(statement_sequence, emit, context,
                                   allow_none = False):

    if statement_sequence is None and allow_none:
        return

    for statement in statement_sequence.getStatements():
        source_ref = statement.getSourceReference()

        if Options.shallTraceExecution():
            statement_repr = repr(statement)
            source_repr = source_ref.getAsString()

            if Utils.python_version >= 300:
                statement_repr = statement_repr.encode("utf8")
                source_repr = source_repr.encode("utf8")

            emit(
                Generator.getStatementTrace(
                    source_repr,
                    statement_repr
                )
            )

        if statement.isStatementsSequence():
            code = "\n".join(
                generateStatementSequenceCode(
                    statement_sequence = statement,
                    context            = context
                )
            )

            code = code.strip()

            emit(code)
        else:
            if statement.needsLineNumber():
                Generator.getSetLineNumberCode(
                    source_ref = source_ref,
                    emit       = emit,
                    context    = context
                )

            generateStatementCode(
                statement = statement,
                emit      = emit,
                context   = context
            )


def generateStatementSequenceCode(statement_sequence, context,
                                  allow_none = False):

    if allow_none and statement_sequence is None:
        return None

    assert statement_sequence.isStatementsSequence(), statement_sequence

    statement_context = Contexts.PythonStatementCContext(context)

    # Frame context or normal statement context.
    if statement_sequence.isStatementsFrame():
        guard_mode = statement_sequence.getGuardMode()

        parent_exception_exit = statement_context.getExceptionEscape()

        if guard_mode != "pass_through":
            statement_context.setExceptionEscape(
                statement_context.allocateLabel("frame_exception_exit")
            )
        else:
            context.setFrameHandle("PyThreadState_GET()->frame")

        needs_preserve = statement_sequence.needsFrameExceptionPreserving()

        if statement_sequence.mayReturn():
            parent_return_exit = statement_context.getReturnTarget()

            statement_context.setReturnTarget(
                statement_context.allocateLabel("frame_return_exit")
            )
        else:
            parent_return_exit = None

    emit = Emission.SourceCodeCollector()

    # print statement_sequence.source_ref, len(statements)

    _generateStatementSequenceCode(
        statement_sequence = statement_sequence,
        emit               = emit,
        context            = statement_context
    )

    # Complain if any temporary was not dealt with yet.
    assert not statement_context.getCleanupTempnames(), \
      statement_context.getCleanupTempnames()

    if statement_sequence.isStatementsFrame():
        provider = statement_sequence.getParentVariableProvider()

        if statement_sequence.mayRaiseException(BaseException) or \
           guard_mode == "generator":
            frame_exception_exit = statement_context.getExceptionEscape()
        else:
            frame_exception_exit = None

        if parent_return_exit is not None:
            frame_return_exit = statement_context.getReturnTarget()
        else:
            frame_return_exit = None

        if guard_mode == "generator":
            assert provider.isExpressionFunctionBody() and \
                   provider.isGenerator()

            # TODO: This case should care about "needs_preserve", as for
            # Python3 it is actually not a stub of empty code.

            codes = Generator.getFrameGuardLightCode(
                frame_identifier      = context.getFrameHandle(),
                code_identifier       = statement_sequence.getCodeObjectHandle(
                    context = context
                ),
                codes                 = emit.codes,
                parent_exception_exit = parent_exception_exit,
                frame_exception_exit  = frame_exception_exit,
                parent_return_exit    = parent_return_exit,
                frame_return_exit     = frame_return_exit,
                provider              = provider,
                context               = statement_context
            ).split("\n")
        elif guard_mode == "pass_through":
            assert provider.isExpressionFunctionBody()

            # This case does not care about "needs_preserve", as for that kind
            # of frame, it is an empty code stub anyway.
            codes = "\n".join(emit.codes),
        elif guard_mode == "full":
            assert provider.isExpressionFunctionBody()

            codes = Generator.getFrameGuardHeavyCode(
                frame_identifier      = context.getFrameHandle(),
                code_identifier       = statement_sequence.getCodeObjectHandle(
                    context
                ),
                parent_exception_exit = parent_exception_exit,
                parent_return_exit    = parent_return_exit,
                frame_exception_exit  = frame_exception_exit,
                frame_return_exit     = frame_return_exit,
                codes                 = emit.codes,
                needs_preserve        = needs_preserve,
                provider              = provider,
                context               = statement_context
            ).split("\n")
        elif guard_mode == "once":
            codes = Generator.getFrameGuardOnceCode(
                frame_identifier      = context.getFrameHandle(),
                code_identifier       = statement_sequence.getCodeObjectHandle(
                    context = context
                ),
                parent_exception_exit = parent_exception_exit,
                parent_return_exit    = parent_return_exit,
                frame_exception_exit  = frame_exception_exit,
                frame_return_exit     = frame_return_exit,
                codes                 = emit.codes,
                needs_preserve        = needs_preserve,
                provider              = provider,
                context               = statement_context
            ).split("\n")
        else:
            assert False, guard_mode

        context.setExceptionEscape(parent_exception_exit)

        if frame_return_exit is not None:
            context.setReturnTarget(parent_return_exit)
    else:
        codes = emit.codes

    return codes


def generateModuleCode(global_context, module, module_name, other_modules):
    assert module.isPythonModule(), module

    context = Contexts.PythonModuleContext(
        module_name    = module_name,
        code_name      = Generator.getModuleIdentifier(module_name),
        filename       = module.getFilename(),
        global_context = global_context,
        is_empty       = module.getBody() is None
    )

    context.setExceptionEscape("module_exception_exit")

    statement_sequence = module.getBody()

    codes = generateStatementSequenceCode(
        statement_sequence = statement_sequence,
        allow_none         = True,
        context            = context,
    )

    codes = codes or []

    function_decl_codes = []
    function_body_codes = []
    extra_declarations = []

    for function_body in module.getUsedFunctions():
        function_code = generateFunctionBodyCode(
            function_body = function_body,
            context       = context
        )

        assert type( function_code ) is str

        function_body_codes.append( function_code )

        if function_body.needsDirectCall():
            function_decl = Generator.getFunctionDirectDecl(
                function_identifier = function_body.getCodeName(),
                closure_variables   = function_body.getClosureVariables(),
                parameter_variables = function_body.getParameters().getAllVariables(),
                file_scope          = Generator.getExportScopeCode(
                    cross_module = function_body.isCrossModuleUsed()
                )
            )

            if function_body.isCrossModuleUsed():
                extra_declarations.append( function_decl )
            else:
                function_decl_codes.append( function_decl )

    for _identifier, code in sorted( iterItems( context.getHelperCodes() ) ):
        function_body_codes.append( code )

    for _identifier, code in sorted( iterItems( context.getDeclarations() ) ):
        function_decl_codes.append( code )

    function_body_codes = "\n\n".join( function_body_codes )
    function_decl_codes = "\n\n".join( function_decl_codes )

    metapath_loader_inittab = []

    for other_module in other_modules:
        metapath_loader_inittab.append(
            Generator.getModuleMetapathLoaderEntryCode(
                module_name = other_module.getFullName(),
                is_shlib    = other_module.isPythonShlibModule()
            )
        )


    module_source_code = Generator.getModuleCode(
        module_name             = module_name,
        codes                   = codes,
        metapath_loader_inittab = metapath_loader_inittab,
        function_decl_codes     = function_decl_codes,
        function_body_codes     = function_body_codes,
        temp_variables          = module.getTempVariables(),
        context                 = context,
    )

    extra_declarations = "\n".join( extra_declarations )

    module_header_code = Generator.getModuleDeclarationCode(
        module_name        = module_name,
        extra_declarations = extra_declarations
    )

    return module_source_code, module_header_code, context


def generateMainCode(main_module, codes, context):
    return Generator.getMainCode(
        main_module = main_module,
        context     = context,
        codes       = codes
    )


def generateConstantsDeclarationCode(context):
    return Generator.getConstantsDeclarationCode(
        context = context
    )


def generateConstantsDefinitionCode(context):
    return Generator.getConstantsDefinitionCode(
        context = context
    )


def generateHelpersCode():
    header_code = Generator.getCallsDecls()

    body_code = Generator.getCallsCode()

    return header_code, body_code


def makeGlobalContext():
    return Contexts.PythonGlobalContext()
