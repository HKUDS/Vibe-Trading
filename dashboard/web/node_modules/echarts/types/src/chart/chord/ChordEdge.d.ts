import type { PathProps } from 'zrender/lib/graphic/Path.js';
import type PathProxy from 'zrender/lib/core/PathProxy.js';
import * as graphic from '../../util/graphic.js';
import SeriesData from '../../data/SeriesData.js';
import ChordSeriesModel from './ChordSeries.js';
export declare class ChordPathShape {
    s1: [number, number];
    s2: [number, number];
    sStartAngle: number;
    sEndAngle: number;
    t1: [number, number];
    t2: [number, number];
    tStartAngle: number;
    tEndAngle: number;
    cx: number;
    cy: number;
    r: number;
    clockwise: boolean;
}
interface ChordEdgePathProps extends PathProps {
    shape?: Partial<ChordPathShape>;
}
export declare class ChordEdge extends graphic.Path<ChordEdgePathProps> {
    shape: ChordPathShape;
    constructor(nodeData: SeriesData<ChordSeriesModel>, edgeData: SeriesData, edgeIdx: number, startAngle: number);
    buildPath(ctx: PathProxy | CanvasRenderingContext2D, shape: ChordPathShape): void;
    updateData(nodeData: SeriesData<ChordSeriesModel>, edgeData: SeriesData, edgeIdx: number, startAngle: number, firstCreate?: boolean): void;
}
export {};
