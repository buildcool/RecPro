declare module 'justified-layout' {
  type Box = { aspectRatio: number; top: number; left: number; width: number; height: number };
  type Result = { containerHeight: number; widowCount: number; boxes: Box[] };
  type Options = {
    containerWidth?: number;
    containerPadding?: number | { top: number; right: number; bottom: number; left: number };
    boxSpacing?: number | { horizontal: number; vertical: number };
    targetRowHeight?: number;
    targetRowHeightTolerance?: number;
    maxNumRows?: number;
    forceAspectRatio?: boolean | number;
    showWidows?: boolean;
    fullWidthBreakoutRowCadence?: boolean | number;
  };
  export default function justifiedLayout(input: number[], options?: Options): Result;
}
