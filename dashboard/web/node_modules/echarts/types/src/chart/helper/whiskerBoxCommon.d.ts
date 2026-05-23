import type { SeriesOption, SeriesOnCartesianOptionMixin, LayoutOrient } from '../../util/types.js';
import type GlobalModel from '../../model/Global.js';
import type SeriesModel from '../../model/Series.js';
import type SeriesData from '../../data/SeriesData.js';
import type Axis2D from '../../coord/cartesian/Axis2D.js';
import { CoordDimensionDefinition } from '../../data/helper/createDimensions.js';
import { CoordinateSystemClipArea } from '../../coord/CoordinateSystem.js';
import { ShapeClipKind } from './createClipPathFromCoordSys.js';
interface CommonOption extends SeriesOption, SeriesOnCartesianOptionMixin {
    layout?: LayoutOrient;
}
export interface WhiskerBoxCommonMixin<Opts extends CommonOption> extends SeriesModel<Opts> {
}
export declare class WhiskerBoxCommonMixin<Opts extends CommonOption> {
    private _baseAxisDim;
    defaultValueDimensions: CoordDimensionDefinition['dimsDef'];
    /**
     * Computed layout.
     */
    private _layout;
    /**
     * @private
     */
    _hasEncodeRule(key: string): boolean;
    /**
     * @override
     */
    getInitialData(option: Opts, ecModel: GlobalModel): SeriesData;
    /**
     * If horizontal, base axis is x, otherwise y.
     * @override
     */
    getBaseAxis(): Axis2D;
    getWhiskerBoxesLayout(): LayoutOrient;
}
/**
 * PENDING: We do not use zr Element clipPath due to performance consideration,
 * although it may be further optimized.
 */
export declare function resolveNormalBoxClipping(clipArea: CoordinateSystemClipArea, itemLayout: {
    ends: number[][];
}): ShapeClipKind;
export {};
