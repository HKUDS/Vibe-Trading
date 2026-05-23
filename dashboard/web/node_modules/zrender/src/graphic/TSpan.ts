import Displayable, { DisplayableProps, DisplayableStatePropNames } from './Displayable';
import BoundingRect from '../core/BoundingRect';
import { PathStyleProps, DEFAULT_PATH_STYLE } from './Path';
import { createObject, defaults } from '../core/util';
import { FontStyle, FontWeight } from '../core/types';
import { DEFAULT_FONT } from '../core/platform';
import { tSpanCreateBoundingRect, tSpanHasStroke } from './helper/parseText';

export interface TSpanStyleProps extends PathStyleProps {

    x?: number
    y?: number

    // TODO Text is assigned inside zrender
    text?: string

    // Final generated font string
    // Used in canvas, and when developers specified it.
    font?: string

    // Value for each part of font
    // Used in svg.
    // NOTE: font should always been sync with these 4 properties.
    fontSize?: number
    fontWeight?: FontWeight
    fontStyle?: FontStyle
    fontFamily?: string

    textAlign?: CanvasTextAlign

    textBaseline?: CanvasTextBaseline
}

export const DEFAULT_TSPAN_STYLE: TSpanStyleProps = defaults({
    strokeFirst: true,
    font: DEFAULT_FONT,
    x: 0,
    y: 0,
    textAlign: 'left',
    textBaseline: 'top',
    miterLimit: 2
} as TSpanStyleProps, DEFAULT_PATH_STYLE);


export interface TSpanProps extends DisplayableProps {
    style?: TSpanStyleProps
}

export type TSpanState = Pick<TSpanProps, DisplayableStatePropNames>

class TSpan extends Displayable<TSpanProps> {

    style: TSpanStyleProps

    hasStroke() {
        return tSpanHasStroke(this.style);
    }

    hasFill() {
        const style = this.style;
        const fill = style.fill;
        return fill != null && fill !== 'none';
    }

    /**
     * Create an image style object with default values in it's prototype.
     * @override
     */
    createStyle(obj?: TSpanStyleProps) {
        return createObject(DEFAULT_TSPAN_STYLE, obj);
    }

    /**
     * Set bounding rect calculated from Text
     * For reducing time of calculating bounding rect.
     */
    setBoundingRect(rect: BoundingRect) {
        this._rect = rect;
    }

    getBoundingRect(): BoundingRect {
        if (!this._rect) {
            this._rect = tSpanCreateBoundingRect(this.style);
        }

        return this._rect;
    }

    protected static initDefaultProps = (function () {
        const tspanProto = TSpan.prototype;
        // TODO Calculate tolerance smarter
        tspanProto.dirtyRectTolerance = 10;
    })()
}

TSpan.prototype.type = 'tspan';

export default TSpan;