import { __extends } from "tslib";
import Displayable from './Displayable.js';
import { DEFAULT_PATH_STYLE } from './Path.js';
import { createObject, defaults } from '../core/util.js';
import { DEFAULT_FONT } from '../core/platform.js';
import { tSpanCreateBoundingRect, tSpanHasStroke } from './helper/parseText.js';
export var DEFAULT_TSPAN_STYLE = defaults({
    strokeFirst: true,
    font: DEFAULT_FONT,
    x: 0,
    y: 0,
    textAlign: 'left',
    textBaseline: 'top',
    miterLimit: 2
}, DEFAULT_PATH_STYLE);
var TSpan = (function (_super) {
    __extends(TSpan, _super);
    function TSpan() {
        return _super !== null && _super.apply(this, arguments) || this;
    }
    TSpan.prototype.hasStroke = function () {
        return tSpanHasStroke(this.style);
    };
    TSpan.prototype.hasFill = function () {
        var style = this.style;
        var fill = style.fill;
        return fill != null && fill !== 'none';
    };
    TSpan.prototype.createStyle = function (obj) {
        return createObject(DEFAULT_TSPAN_STYLE, obj);
    };
    TSpan.prototype.setBoundingRect = function (rect) {
        this._rect = rect;
    };
    TSpan.prototype.getBoundingRect = function () {
        if (!this._rect) {
            this._rect = tSpanCreateBoundingRect(this.style);
        }
        return this._rect;
    };
    TSpan.initDefaultProps = (function () {
        var tspanProto = TSpan.prototype;
        tspanProto.dirtyRectTolerance = 10;
    })();
    return TSpan;
}(Displayable));
TSpan.prototype.type = 'tspan';
export default TSpan;
