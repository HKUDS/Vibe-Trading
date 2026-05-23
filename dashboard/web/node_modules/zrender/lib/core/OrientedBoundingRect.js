import Point from './Point.js';
import { createIntersectContext } from './BoundingRect.js';
var mathMin = Math.min;
var mathMax = Math.max;
var mathAbs = Math.abs;
var _extent = [0, 0];
var _extent2 = [0, 0];
var _intersectCtx = createIntersectContext();
var _minTv = _intersectCtx.minTv;
var _maxTv = _intersectCtx.maxTv;
var OrientedBoundingRect = (function () {
    function OrientedBoundingRect(rect, transform) {
        this._corners = [];
        this._axes = [];
        this._origin = [0, 0];
        for (var i = 0; i < 4; i++) {
            this._corners[i] = new Point();
        }
        for (var i = 0; i < 2; i++) {
            this._axes[i] = new Point();
        }
        if (rect) {
            this.fromBoundingRect(rect, transform);
        }
    }
    OrientedBoundingRect.prototype.fromBoundingRect = function (rect, transform) {
        var corners = this._corners;
        var axes = this._axes;
        var x = rect.x;
        var y = rect.y;
        var x2 = x + rect.width;
        var y2 = y + rect.height;
        corners[0].set(x, y);
        corners[1].set(x2, y);
        corners[2].set(x2, y2);
        corners[3].set(x, y2);
        if (transform) {
            for (var i = 0; i < 4; i++) {
                corners[i].transform(transform);
            }
        }
        Point.sub(axes[0], corners[1], corners[0]);
        Point.sub(axes[1], corners[3], corners[0]);
        axes[0].normalize();
        axes[1].normalize();
        for (var i = 0; i < 2; i++) {
            this._origin[i] = axes[i].dot(corners[0]);
        }
    };
    OrientedBoundingRect.prototype.intersect = function (other, mtv, opt) {
        var overlapped = true;
        var noMtv = !mtv;
        if (mtv) {
            Point.set(mtv, 0, 0);
        }
        _intersectCtx.reset(opt, !noMtv);
        if (!this._intersectCheckOneSide(this, other, noMtv, 1)) {
            overlapped = false;
            if (noMtv) {
                return overlapped;
            }
        }
        if (!this._intersectCheckOneSide(other, this, noMtv, -1)) {
            overlapped = false;
            if (noMtv) {
                return overlapped;
            }
        }
        if (!noMtv && !_intersectCtx.negativeSize) {
            Point.copy(mtv, overlapped
                ? (_intersectCtx.useDir ? _intersectCtx.dirMinTv : _minTv)
                : _maxTv);
        }
        return overlapped;
    };
    OrientedBoundingRect.prototype._intersectCheckOneSide = function (self, other, noMtv, inverse) {
        var overlapped = true;
        for (var i = 0; i < 2; i++) {
            var axis = self._axes[i];
            self._getProjMinMaxOnAxis(i, self._corners, _extent);
            self._getProjMinMaxOnAxis(i, other._corners, _extent2);
            if (_intersectCtx.negativeSize || _extent[1] < _extent2[0] || _extent[0] > _extent2[1]) {
                overlapped = false;
                if (_intersectCtx.negativeSize || noMtv) {
                    return overlapped;
                }
                var dist0 = mathAbs(_extent2[0] - _extent[1]);
                var dist1 = mathAbs(_extent[0] - _extent2[1]);
                if (mathMin(dist0, dist1) > _maxTv.len()) {
                    if (dist0 < dist1) {
                        Point.scale(_maxTv, axis, -dist0 * inverse);
                    }
                    else {
                        Point.scale(_maxTv, axis, dist1 * inverse);
                    }
                }
            }
            else if (!noMtv) {
                var dist0 = mathAbs(_extent2[0] - _extent[1]);
                var dist1 = mathAbs(_extent[0] - _extent2[1]);
                if (_intersectCtx.useDir || mathMin(dist0, dist1) < _minTv.len()) {
                    if (dist0 < dist1 || !_intersectCtx.bidirectional) {
                        Point.scale(_minTv, axis, dist0 * inverse);
                        if (_intersectCtx.useDir) {
                            _intersectCtx.calcDirMTV();
                        }
                    }
                    if (dist0 >= dist1 || !_intersectCtx.bidirectional) {
                        Point.scale(_minTv, axis, -dist1 * inverse);
                        if (_intersectCtx.useDir) {
                            _intersectCtx.calcDirMTV();
                        }
                    }
                }
            }
        }
        return overlapped;
    };
    OrientedBoundingRect.prototype._getProjMinMaxOnAxis = function (dim, corners, out) {
        var axis = this._axes[dim];
        var origin = this._origin;
        var proj = corners[0].dot(axis) + origin[dim];
        var min = proj;
        var max = proj;
        for (var i = 1; i < corners.length; i++) {
            var proj_1 = corners[i].dot(axis) + origin[dim];
            min = mathMin(proj_1, min);
            max = mathMax(proj_1, max);
        }
        out[0] = min + _intersectCtx.touchThreshold;
        out[1] = max - _intersectCtx.touchThreshold;
        _intersectCtx.negativeSize = out[1] < out[0];
    };
    return OrientedBoundingRect;
}());
export default OrientedBoundingRect;
