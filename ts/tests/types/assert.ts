export type Equal<Actual, Expected> =
  (<Type>() => Type extends Actual ? 1 : 2) extends <Type>() => Type extends Expected ? 1 : 2
    ? true
    : false;

export type Expect<Value extends true> = Value;
