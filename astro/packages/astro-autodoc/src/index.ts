import AutodocClass from './components/AutodocClass.astro'
import AutodocFunction from './components/AutodocFunction.astro'
import AutodocModule from './components/AutodocModule.astro'
import AutodocPackage from './components/AutodocPackage.astro'
import AutodocVariable from './components/AutodocVariable.astro'
import Docstring from './components/Docstring.astro'

export { AutodocPackage, AutodocModule, AutodocClass, AutodocFunction, AutodocVariable, Docstring }

export const autodocComponents = {
  AutodocPackage,
  AutodocModule,
  AutodocClass,
  AutodocFunction,
  AutodocVariable,
  Docstring,
}

export * from './docstrings.ts'
export * from './load.ts'
export * from './utils.ts'
