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

from nuitka import Utils, SyntaxErrors, Options

from nuitka.nodes.VariableRefNodes import (
    ExpressionTargetTempVariableRef,
    ExpressionTempVariableRef
)
from nuitka.nodes.ConstantRefNodes import ExpressionConstantRef
from nuitka.nodes.ExceptionNodes import (
    ExpressionCaughtExceptionValueRef,
    ExpressionCaughtExceptionTypeRef,
    StatementRaiseException
)
from nuitka.nodes.BuiltinRefNodes import ExpressionBuiltinExceptionRef
from nuitka.nodes.ComparisonNodes import (
    ExpressionComparisonExceptionMatch,
    ExpressionComparisonIs
)
from nuitka.nodes.StatementNodes import (
    StatementPreserveFrameException,
    StatementRestoreFrameException,
    StatementPublishException,
    StatementsSequence
)
from nuitka.nodes.ConditionalNodes import StatementConditional
from nuitka.nodes.AssignNodes import StatementAssignmentVariable
from nuitka.nodes.TryNodes import (
    StatementTryFinally,
    StatementTryExcept
)

from .ReformulationAssignmentStatements import (
    buildDeleteStatementFromDecoded,
    buildAssignmentStatements,
    decodeAssignTarget
)


from .Helpers import(
    makeStatementsSequenceFromStatement,
    makeStatementsSequence,
    buildStatementsNode,
    mergeStatements,
    buildNode
)


def makeTryExceptNoRaise(provider, temp_scope, tried, handling, no_raise,
                         public_exc, source_ref):
    # This helper executes the core re-formulation of "no_raise" blocks, which
    # are the "else" blocks of "try"/"except" statements. In order to limit the
    # execution, we use an indicator variable instead, which will signal that
    # the tried block executed up to the end. And then we make the else block be
    # a conditional statement checking that.

    # This is a separate function, so it can be re-used in other
    # re-formulations, e.g. with statements.

    assert no_raise is not None

    tmp_handler_indicator_variable = provider.allocateTempVariable(
        temp_scope = temp_scope,
        name       = "unhandled_indicator"
    )

    statements = mergeStatements(
        (
            StatementAssignmentVariable(
                variable_ref = ExpressionTargetTempVariableRef(
                    variable   = tmp_handler_indicator_variable.makeReference(
                        provider
                    ),
                    source_ref = source_ref.atInternal()
                ),
                source       = ExpressionConstantRef(
                    constant   = False,
                    source_ref = source_ref
                ),
                source_ref   = no_raise.getSourceReference().atInternal()
            ),
            handling
        ),
        allow_none = True
    )

    handling = StatementsSequence(
        statements = statements,
        source_ref = source_ref
    )

    statements = (
        StatementAssignmentVariable(
            variable_ref = ExpressionTargetTempVariableRef(
                variable   = tmp_handler_indicator_variable.makeReference(
                    provider
                ),
                source_ref = source_ref.atInternal()
            ),
            source     = ExpressionConstantRef(
                constant   = True,
                source_ref = source_ref
            ),
            source_ref = source_ref
        ),
        StatementTryExcept(
            tried      = tried,
            handling   = handling,
            public_exc = public_exc,
            source_ref = source_ref
        ),
        StatementConditional(
            condition  = ExpressionComparisonIs(
                left = ExpressionTempVariableRef(
                    variable   = tmp_handler_indicator_variable.makeReference(
                        provider
                    ),
                    source_ref = source_ref
                ),
                right = ExpressionConstantRef(
                    constant   = True,
                    source_ref = source_ref
                ),
                source_ref = source_ref
            ),
            yes_branch = no_raise,
            no_branch  = None,
            source_ref = source_ref
        )
    )

    return StatementsSequence(
        statements = statements,
        source_ref = source_ref
    )


def makeReraiseExceptionStatement(source_ref):
    return StatementsSequence(
        statements = (
            StatementRaiseException(
                exception_type = None,
                exception_value = None,
                exception_trace = None,
                exception_cause = None,
                source_ref      = source_ref
            ),
        ),
        source_ref  = source_ref
    )

def makeTryExceptSingleHandlerNode(tried, exception_name, handler_body,
                                   public_exc, source_ref):
    if public_exc:
        statements = [
            StatementPreserveFrameException(
                source_ref = source_ref.atInternal()
            ),
            StatementPublishException(
                source_ref = source_ref.atInternal()
            )
        ]
    else:
        statements = []

    statements.append(
        StatementConditional(
            condition = ExpressionComparisonExceptionMatch(
                left      = ExpressionCaughtExceptionTypeRef(
                    source_ref  = source_ref
                ),
                right     = ExpressionBuiltinExceptionRef(
                    exception_name = exception_name,
                    source_ref     = source_ref
                ),
                source_ref = source_ref
            ),
            yes_branch = handler_body,
            no_branch  = makeReraiseExceptionStatement(
                source_ref = source_ref
            ),
            source_ref = source_ref
        )
    )

    if Utils.python_version >= 300 and public_exc:
        statements = [
            StatementTryFinally(
                tried      = StatementsSequence(
                    statements = statements,
                    source_ref = source_ref
                ),
                final      = makeStatementsSequenceFromStatement(
                    statement = StatementRestoreFrameException(
                        source_ref = source_ref.atInternal()
                    )
                ),
                public_exc = False,
                source_ref = source_ref.atInternal()
            )
        ]

    return StatementTryExcept(
        tried      = tried,
        handling   = StatementsSequence(
            statements = statements,
            source_ref = source_ref
        ),
        public_exc = public_exc,
        source_ref = source_ref
    )


def buildTryExceptionNode(provider, node, source_ref):
    # Try/except nodes. Re-formulated as described in the developer
    # manual. Exception handlers made the assignment to variables explicit. Same
    # for the "del" as done for Python3. Also catches always work a tuple of
    # exception types and hides away that they may be built or not.

    # Many variables, due to the re-formulation that is going on here, which
    # just has the complexity, pylint: disable=R0914

    tried = buildStatementsNode(
        provider   = provider,
        nodes      = node.body,
        source_ref = source_ref
    )

    handlers = []

    for handler in node.handlers:
        exception_expression, exception_assign, exception_block = (
            handler.type,
            handler.name,
            handler.body
        )

        if exception_assign is None:
            statements = [
                buildStatementsNode(
                    provider   = provider,
                    nodes      = exception_block,
                    source_ref = source_ref
                )
            ]
        elif Utils.python_version < 300:
            statements = [
                buildAssignmentStatements(
                    provider   = provider,
                    node       = exception_assign,
                    source     = ExpressionCaughtExceptionValueRef(
                        source_ref = source_ref.atInternal()
                    ),
                    source_ref = source_ref.atInternal()
                ),
                buildStatementsNode(
                    provider   = provider,
                    nodes      = exception_block,
                    source_ref = source_ref
                )
            ]
        else:
            target_info = decodeAssignTarget(
                provider   = provider,
                node       = exception_assign,
                source_ref = source_ref,
            )

            kind, detail = target_info

            assert kind == "Name", kind
            kind = "Name_Exception"

            statements = [
                buildAssignmentStatements(
                    provider   = provider,
                    node       = exception_assign,
                    source     = ExpressionCaughtExceptionValueRef(
                        source_ref = source_ref.atInternal()
                    ),
                    source_ref = source_ref.atInternal()
                ),
                StatementTryFinally(
                    tried      = buildStatementsNode(
                        provider   = provider,
                        nodes      = exception_block,
                        source_ref = source_ref
                    ),
                    final      = StatementsSequence(
                        statements = (
                            buildDeleteStatementFromDecoded(
                                kind       = kind,
                                detail     = detail,
                                source_ref = source_ref
                            ),
                        ),
                        source_ref = source_ref
                    ),
                    public_exc = False,
                    source_ref = source_ref
                )
            ]

        handler_body = makeStatementsSequence(
            statements = statements,
            allow_none = True,
            source_ref = source_ref
        )

        exception_types = buildNode(
            provider   = provider,
            node       = exception_expression,
            source_ref = source_ref,
            allow_none = True
        )

        # The exception types should be a tuple, so as to be most general.
        if exception_types is None:
            if handler is not node.handlers[-1]:
                SyntaxErrors.raiseSyntaxError(
                    reason    = "default 'except:' must be last",
                    source_ref = source_ref.atLineNumber(
                        handler.lineno-1
                          if Options.isFullCompat() else
                        handler.lineno
                    )
                )

        handlers.append(
            (
                exception_types,
                handler_body,
            )
        )

    # Reraise by default
    exception_handling = makeReraiseExceptionStatement(
        source_ref  = source_ref
    )

    for exception_type, handler in reversed(handlers):
        if exception_type is None:
            # A default handler was given, so use that indead.
            exception_handling = handler
        else:
            exception_handling = StatementsSequence(
                statements = (
                    StatementConditional(
                        condition = ExpressionComparisonExceptionMatch(
                            left       = ExpressionCaughtExceptionTypeRef(
                                source_ref  = exception_type.source_ref
                            ),
                            right      = exception_type,
                            source_ref = exception_type.source_ref
                        ),
                        yes_branch = handler,
                        no_branch  = exception_handling,
                        source_ref = exception_type.source_ref
                    ),
                ),
                source_ref = exception_type.source_ref
            )

    prelude = (
        StatementPreserveFrameException(
            source_ref = source_ref.atInternal()
        ),
        StatementPublishException(
            source_ref = source_ref.atInternal()
        )
    )

    if exception_handling is None:
        # For Python3, we need not publish at all, if all we do is to revert
        # that immediately. For Python2, the publish may release previously
        # published exception, which has side effects potentially.
        if Utils.python_version < 300:
            exception_handling = StatementsSequence(
                statements = prelude,
                source_ref = source_ref.atInternal()
            )

            public_exc = True
        else:
            public_exc = False
    else:
        public_exc = True

        if Utils.python_version < 300:
            exception_handling.setStatements(
                prelude + exception_handling.getStatements()
            )
        else:
            exception_handling = StatementsSequence(
                statements = prelude + (
                    StatementTryFinally(
                        tried = exception_handling,
                        final = makeStatementsSequenceFromStatement(
                            statement = StatementRestoreFrameException(
                                source_ref = source_ref.atInternal()
                            ),
                        ),
                        public_exc = False,
                        source_ref = source_ref.atInternal()
                    ),
                ),
                source_ref = source_ref.atInternal()
            )

    no_raise = buildStatementsNode(
        provider   = provider,
        nodes      = node.orelse,
        source_ref = source_ref
    )

    if no_raise is None:
        return StatementTryExcept(
            tried      = tried,
            handling   = exception_handling,
            public_exc = public_exc,
            source_ref = source_ref
        )
    else:
        return makeTryExceptNoRaise(
            provider   = provider,
            temp_scope = provider.allocateTempScope("try_except"),
            handling   = exception_handling,
            tried      = tried,
            public_exc = public_exc,
            no_raise   = no_raise,
            source_ref = source_ref
        )
