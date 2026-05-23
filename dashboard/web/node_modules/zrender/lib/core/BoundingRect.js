import * as matrix from './matrix.js';
import * as vector from './vector.js';
import Point from './Point.js';
var mathMin = Math.min;
var mathMax = Math.max;
var mathAbs = Math.abs;
var XY = ['x', 'y'];
var WH = ['width', 'height'];
var lt = new Point();
var rb = new Point();
var lb = new Point();
var rt = new Point();
var _intersectCtx = createIntersectContext();
var _minTv = _intersectCtx.minTv;
var _maxTv = _intersectCtx.maxTv;
var _lenMinMax = [0, 0];
var BoundingRect = (function () {
    function BoundingRect(x, y, width, height) {
        boundingRectSet(this, x, y, width, height);
    }
    BoundingRect.set = function (target, x, y, width, height) {
        if (width < 0) {
            x = x + width;
            width = -width;
        }
        if (height < 0) {
            y = y + height;
            height = -height;
        }
        target.x = x;
        target.y = y;
        target.width = width;
        target.height = height;
        return target;
    };
    BoundingRect.prototype.union = function (other) {
        var x = mathMin(other.x, this.x);
        var y = mathMin(other.y, this.y);
        if (isFinite(this.x) && isFinite(this.width)) {
            this.width = mathMax(other.x + other.width, this.x + this.width) - x;
        }
        else {
            this.width = other.width;
        }
        if (isFinite(this.y) && isFinite(this.height)) {
            this.height = mathMax(other.y + other.height, this.y + this.height) - y;
        }
        else {
            this.height = other.height;
        }
        this.x = x;
        this.y = y;
    };
    BoundingRect.prototype.applyTransform = function (m) {
        BoundingRect.applyTransform(this, this, m);
    };
    BoundingRect.prototype.calculateTransform = function (b) {
        return boundingRectCalculateTransform(matrix.create(), this, b);
    };
    BoundingRect.prototype.intersect = function (b, mtv, opt) {
        return BoundingRect.intersect(this, b, mtv, opt);
    };
    BoundingRect.intersect = function (a, b, mtv, opt) {
        if (mtv) {
            Point.set(mtv, 0, 0);
        }
        var outIntersectRect = opt && opt.outIntersectRect || null;
        var clamp = opt && opt.clamp;
        if (outIntersectRect) {
            outIntersectRect.x = outIntersectRect.y = outIntersectRect.width = outIntersectRect.height = NaN;
        }
        if (!a || !b) {
            return false;
        }
        if (!(a instanceof BoundingRect)) {
            a = boundingRectSet(_tmpIntersectA, a.x, a.y, a.width, a.height);
        }
        if (!(b instanceof BoundingRect)) {
            b = boundingRectSet(_tmpIntersectB, b.x, b.y, b.width, b.height);
        }
        var useMTV = !!mtv;
        _intersectCtx.reset(opt, useMTV);
        var touchThreshold = _intersectCtx.touchThreshold;
        var ax0 = a.x + touchThreshold;
        var ax1 = a.x + a.width - touchThreshold;
        var ay0 = a.y + touchThreshold;
        var ay1 = a.y + a.height - touchThreshold;
        var bx0 = b.x + touchThreshold;
        var bx1 = b.x + b.width - touchThreshold;
        var by0 = b.y + touchThreshold;
        var by1 = b.y + b.height - touchThreshold;
        if (ax0 > ax1 || ay0 > ay1 || bx0 > bx1 || by0 > by1) {
            return false;
        }
        var overlap = !(ax1 < bx0 || bx1 < ax0 || ay1 < by0 || by1 < ay0);
        if (useMTV || outIntersectRect) {
            _lenMinMax[0] = Infinity;
            _lenMinMax[1] = 0;
            intersectOneDim(ax0, ax1, bx0, bx1, 0, useMTV, outIntersectRect, clamp);
            intersectOneDim(ay0, ay1, by0, by1, 1, useMTV, outIntersectRect, clamp);
            if (useMTV) {
                Point.copy(mtv, overlap
                    ? (_intersectCtx.useDir ? _intersectCtx.dirMinTv : _minTv)
                    : _maxTv);
            }
        }
        return overlap;
    };
    BoundingRect.contain = function (rect, x, y) {
        return x >= rect.x
            && x <= (rect.x + rect.width)
            && y >= rect.y
            && y <= (rect.y + rect.height);
    };
    BoundingRect.prototype.contain = function (x, y) {
        return BoundingRect.contain(this, x, y);
    };
    BoundingRect.prototype.clone = function () {
        return new BoundingRect(this.x, this.y, this.width, this.height);
    };
    BoundingRect.prototype.copy = function (other) {
        boundingRectCopy(this, other);
    };
    BoundingRect.prototype.plain = function () {
        return {
            x: this.x,
            y: this.y,
            width: this.width,
            height: this.height
        };
    };
    BoundingRect.prototype.isFinite = function () {
        return isFinite(this.x)
            && isFinite(this.y)
            && isFinite(this.width)
            && isFinite(this.height);
    };
    BoundingRect.prototype.isZero = function () {
        return this.width === 0 || this.height === 0;
    };
    BoundingRect.create = function (rect) {
        return new BoundingRect(rect ? rect.x : 0, rect ? rect.y : 0, rect ? rect.width : 0, rect ? rect.height : 0);
    };
    BoundingRect.copy = function (target, source) {
        target.x = source.x;
        target.y = source.y;
        target.width = source.width;
        target.height = source.height;
        return target;
    };
    BoundingRect.applyTransform = function (target, source, m) {
        if (!m) {
            if (target !== source) {
                boundingRectCopy(target, source);
            }
            return;
        }
        if (m[1] < 1e-5 && m[1] > -1e-5 && m[2] < 1e-5 && m[2] > -1e-5) {
            var sx = m[0];
            var sy = m[3];
            var tx = m[4];
            var ty = m[5];
            target.x = source.x * sx + tx;
            target.y = source.y * sy + ty;
            target.width = source.width * sx;
            target.height = source.height * sy;
            if (target.width < 0) {
                target.x += target.width;
                target.width = -target.width;
            }
            if (target.height < 0) {
                target.y += target.height;
                target.height = -target.height;
            }
            return;
        }
        lt.x = lb.x = source.x;
        lt.y = rt.y = source.y;
        rb.x = rt.x = source.x + source.width;
        rb.y = lb.y = source.y + source.height;
        lt.transform(m);
        rt.transform(m);
        rb.transform(m);
        lb.transform(m);
        target.x = mathMin(lt.x, rb.x, lb.x, rt.x);
        target.y = mathMin(lt.y, rb.y, lb.y, rt.y);
        var maxX = mathMax(lt.x, rb.x, lb.x, rt.x);
        var maxY = mathMax(lt.y, rb.y, lb.y, rt.y);
        target.width = maxX - target.x;
        target.height = maxY - target.y;
    };
    BoundingRect.calculateTransform = function (out, a, b) {
        var sx = b.width / a.width;
        var sy = b.height / a.height;
        out = matrix.identity(out || []);
        matrix.translate(out, out, vector.set(_tmpCalcTrans, -a.x, -a.y));
        matrix.scale(out, out, vector.set(_tmpCalcTrans, sx, sy));
        matrix.translate(out, out, vector.set(_tmpCalcTrans, b.x, b.y));
        return out;
    };
    return BoundingRect;
}());
export var boundingRectCreate = BoundingRect.create;
export var boundingRectSet = BoundingRect.set;
export var boundingRectCopy = BoundingRect.copy;
export var boundingRectCalculateTransform = BoundingRect.calculateTransform;
export var boundingRectApplyTransform = BoundingRect.applyTransform;
export var boundingRectContain = BoundingRect.contain;
var _tmpIntersectA = new BoundingRect(0, 0, 0, 0);
var _tmpIntersectB = new BoundingRect(0, 0, 0, 0);
var _tmpCalcTrans = [];
function intersectOneDim(a0, a1, b0, b1, updateDimIdx, useMTV, outIntersectRect, clamp) {
    var d0 = mathAbs(a1 - b0);
    var d1 = mathAbs(b1 - a0);
    var d01min = mathMin(d0, d1);
    var updateDim = XY[updateDimIdx];
    var zeroDim = XY[1 - updateDimIdx];
    var wh = WH[updateDimIdx];
    if (a1 < b0 || b1 < a0) {
        if (d0 < d1) {
            if (useMTV) {
                _maxTv[updateDim] = -d0;
            }
            if (clamp) {
                outIntersectRect[updateDim] = a1;
                outIntersectRect[wh] = 0;
            }
        }
        else {
            if (useMTV) {
                _maxTv[updateDim] = d1;
            }
            if (clamp) {
                outIntersectRect[updateDim] = a0;
                outIntersectRect[wh] = 0;
            }
        }
    }
    else {
        if (outIntersectRect) {
            outIntersectRect[updateDim] = mathMax(a0, b0);
            outIntersectRect[wh] = mathMin(a1, b1) - outIntersectRect[updateDim];
        }
        if (useMTV) {
            if (d01min < _lenMinMax[0] || _intersectCtx.useDir) {
                _lenMinMax[0] = mathMin(d01min, _lenMinMax[0]);
                if (d0 < d1 || !_intersectCtx.bidirectional) {
                    _minTv[updateDim] = d0;
                    _minTv[zeroDim] = 0;
                    if (_intersectCtx.useDir) {
                        _intersectCtx.calcDirMTV();
                    }
                }
                if (d0 >= d1 || !_intersectCtx.bidirectional) {
                    _minTv[updateDim] = -d1;
                    _minTv[zeroDim] = 0;
                    if (_intersectCtx.useDir) {
                        _intersectCtx.calcDirMTV();
                    }
                }
            }
        }
    }
}
export function createIntersectContext() {
    var _direction = 0;
    var _dirCheckVec = new Point();
    var _dirTmp = new Point();
    var _ctx = {
        minTv: new Point(),
        maxTv: new Point(),
        useDir: false,
        dirMinTv: new Point(),
        touchThreshold: 0,
        bidirectional: true,
        negativeSize: false,
        reset: function (opt, useMTV) {
            _ctx.touchThreshold = 0;
            if (opt && opt.touchThreshold != null) {
                _ctx.touchThreshold = mathMax(0, opt.touchThreshold);
            }
            _ctx.negativeSize = false;
            if (!useMTV) {
                return;
            }
            _ctx.minTv.set(Infinity, Infinity);
            _ctx.maxTv.set(0, 0);
            _ctx.useDir = false;
            if (opt && opt.direction != null) {
                _ctx.useDir = true;
                _ctx.dirMinTv.copy(_ctx.minTv);
                _dirTmp.copy(_ctx.minTv);
                _direction = opt.direction;
                _ctx.bidirectional = opt.bidirectional == null || !!opt.bidirectional;
                if (!_ctx.bidirectional) {
                    _dirCheckVec.set(Math.cos(_direction), Math.sin(_direction));
                }
            }
        },
        calcDirMTV: function () {
            var minTv = _ctx.minTv;
            var dirMinTv = _ctx.dirMinTv;
            var squareMag = minTv.y * minTv.y + minTv.x * minTv.x;
            var dirSin = Math.sin(_direction);
            var dirCos = Math.cos(_direction);
            var dotProd = dirSin * minTv.y + dirCos * minTv.x;
            if (nearZero(dotProd)) {
                if (nearZero(minTv.x) && nearZero(minTv.y)) {
                    dirMinTv.set(0, 0);
                }
                return;
            }
            _dirTmp.x = squareMag * dirCos / dotProd;
            _dirTmp.y = squareMag * dirSin / dotProd;
            if (nearZero(_dirTmp.x) && nearZero(_dirTmp.y)) {
                dirMinTv.set(0, 0);
                return;
            }
            if ((_ctx.bidirectional
                || _dirCheckVec.dot(_dirTmp) > 0)
                && _dirTmp.len() < dirMinTv.len()) {
                dirMinTv.copy(_dirTmp);
            }
        }
    };
    function nearZero(val) {
        return mathAbs(val) < 1e-10;
    }
    return _ctx;
}
export default BoundingRect;
