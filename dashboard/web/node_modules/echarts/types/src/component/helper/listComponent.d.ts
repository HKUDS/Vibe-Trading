import * as graphic from '../../util/graphic.js';
import { RectLike } from 'zrender/lib/core/BoundingRect.js';
import { ItemStyleOption, ZRColor } from '../../util/types.js';
import Model from '../../model/Model.js';
interface BackgroundRelatedOption {
    backgroundColor?: ZRColor;
    borderRadius?: number | number[];
    padding?: number | number[];
    itemStyle?: Omit<ItemStyleOption, 'color' | 'opacity'>;
}
export declare function makeBackground(rect: RectLike, componentModel: Model<BackgroundRelatedOption>): graphic.Rect;
export {};
