from tools.parser import TagScript

blocks = [
    TagScript.RandomBlock(),
    TagScript.RangeBlock(),
    TagScript.IfBlock(),
    TagScript.AllBlock(),
    TagScript.AssignmentBlock(),
    TagScript.SubstringBlock(),
    TagScript.EmbedBlock(),
    TagScript.StrfBlock(),
    TagScript.LooseVariableGetterBlock(),
    TagScript.FiftyFiftyBlock(),
    TagScript.PythonBlock(),
    TagScript.AnyBlock(),
    TagScript.BreakBlock(),
    TagScript.StopBlock(),
    TagScript.MathBlock(),
]

engine = TagScript.AsyncInterpreter(blocks)
