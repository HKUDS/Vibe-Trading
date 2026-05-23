
/*
* Licensed to the Apache Software Foundation (ASF) under one
* or more contributor license agreements.  See the NOTICE file
* distributed with this work for additional information
* regarding copyright ownership.  The ASF licenses this file
* to you under the Apache License, Version 2.0 (the
* "License"); you may not use this file except in compliance
* with the License.  You may obtain a copy of the License at
*
*   http://www.apache.org/licenses/LICENSE-2.0
*
* Unless required by applicable law or agreed to in writing,
* software distributed under the License is distributed on an
* "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
* KIND, either express or implied.  See the License for the
* specific language governing permissions and limitations
* under the License.
*/


/**
 * AUTO-GENERATED FILE. DO NOT MODIFY.
 */

/*
* Licensed to the Apache Software Foundation (ASF) under one
* or more contributor license agreements.  See the NOTICE file
* distributed with this work for additional information
* regarding copyright ownership.  The ASF licenses this file
* to you under the Apache License, Version 2.0 (the
* "License"); you may not use this file except in compliance
* with the License.  You may obtain a copy of the License at
*
*   http://www.apache.org/licenses/LICENSE-2.0
*
* Unless required by applicable law or agreed to in writing,
* software distributed under the License is distributed on an
* "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
* KIND, either express or implied.  See the License for the
* specific language governing permissions and limitations
* under the License.
*/
import { __extends } from "tslib";
import ChartView from '../../view/Chart.js';
import * as graphic from '../../util/graphic.js';
import { setStatesStylesFromModel, toggleHoverEmphasis } from '../../util/states.js';
import Path from 'zrender/lib/graphic/Path.js';
import { SERIES_TYPE_BOXPLOT } from './BoxplotSeries.js';
import { saveOldStyle } from '../../animation/basicTransition.js';
import { resolveNormalBoxClipping } from '../helper/whiskerBoxCommon.js';
import { createClipPath, SHAPE_CLIP_KIND_FULLY_CLIPPED, SHAPE_CLIP_KIND_NOT_CLIPPED, SHAPE_CLIP_KIND_PARTIALLY_CLIPPED, updateClipPath } from '../helper/createClipPathFromCoordSys.js';
import { map } from 'zrender/lib/core/util.js';
var BoxplotView = /** @class */function (_super) {
  __extends(BoxplotView, _super);
  function BoxplotView() {
    var _this = _super !== null && _super.apply(this, arguments) || this;
    _this.type = SERIES_TYPE_BOXPLOT;
    return _this;
  }
  BoxplotView.prototype.render = function (seriesModel, ecModel, api) {
    var data = seriesModel.getData();
    var group = this.group;
    var oldData = this._data;
    // There is no old data only when first rendering or switching from
    // stream mode to normal mode, where previous elements should be removed.
    if (!this._data) {
      group.removeAll();
    }
    var constDim = seriesModel.getWhiskerBoxesLayout() === 'horizontal' ? 1 : 0;
    var needClip = seriesModel.get('clip', true);
    var coordSys = seriesModel.coordinateSystem;
    var clipArea = coordSys.getArea && coordSys.getArea();
    var clipPath = needClip && createClipPath(coordSys, false, seriesModel);
    data.diff(oldData).add(function (newIdx) {
      if (data.hasValue(newIdx)) {
        var itemLayout = data.getItemLayout(newIdx);
        var clipKind = needClip ? resolveNormalBoxClipping(clipArea, itemLayout) : SHAPE_CLIP_KIND_NOT_CLIPPED;
        if (clipKind === SHAPE_CLIP_KIND_FULLY_CLIPPED) {
          return;
        }
        var symbolEl = createNormalBox(itemLayout, data, newIdx, constDim, true);
        // One axis tick can corresponds to a group of box items (from different series),
        // so it may be visually misleading when a group of items are partially outside
        // but no clipping is applied.
        // Consider performance of zr Element['clipPath'], only set to partially clipped elements.
        updateClipPath(clipKind === SHAPE_CLIP_KIND_PARTIALLY_CLIPPED, symbolEl, clipPath);
        data.setItemGraphicEl(newIdx, symbolEl);
        group.add(symbolEl);
      }
    }).update(function (newIdx, oldIdx) {
      var symbolEl = oldData.getItemGraphicEl(oldIdx);
      // Empty data
      if (!data.hasValue(newIdx)) {
        group.remove(symbolEl);
        return;
      }
      var itemLayout = data.getItemLayout(newIdx);
      var clipKind = needClip ? resolveNormalBoxClipping(clipArea, itemLayout) : SHAPE_CLIP_KIND_NOT_CLIPPED;
      if (clipKind === SHAPE_CLIP_KIND_FULLY_CLIPPED) {
        group.remove(symbolEl);
        return;
      }
      if (!symbolEl) {
        symbolEl = createNormalBox(itemLayout, data, newIdx, constDim);
      } else {
        saveOldStyle(symbolEl);
        updateNormalBoxData(itemLayout, symbolEl, data, newIdx);
      }
      // See `updateClipPath` in `add`.
      updateClipPath(clipKind === SHAPE_CLIP_KIND_PARTIALLY_CLIPPED, symbolEl, clipPath);
      group.add(symbolEl);
      data.setItemGraphicEl(newIdx, symbolEl);
    }).remove(function (oldIdx) {
      var el = oldData.getItemGraphicEl(oldIdx);
      el && group.remove(el);
    }).execute();
    this._data = data;
  };
  BoxplotView.prototype.remove = function (ecModel) {
    var group = this.group;
    var data = this._data;
    this._data = null;
    data && data.eachItemGraphicEl(function (el) {
      el && group.remove(el);
    });
  };
  BoxplotView.type = SERIES_TYPE_BOXPLOT;
  return BoxplotView;
}(ChartView);
var BoxPathShape = /** @class */function () {
  function BoxPathShape() {}
  return BoxPathShape;
}();
var BoxPath = /** @class */function (_super) {
  __extends(BoxPath, _super);
  function BoxPath(opts) {
    var _this = _super.call(this, opts) || this;
    _this.type = 'boxplotBoxPath';
    return _this;
  }
  BoxPath.prototype.getDefaultShape = function () {
    return new BoxPathShape();
  };
  BoxPath.prototype.buildPath = function (ctx, shape) {
    var ends = shape.points;
    var i = 0;
    ctx.moveTo(ends[i][0], ends[i][1]);
    i++;
    for (; i < 4; i++) {
      ctx.lineTo(ends[i][0], ends[i][1]);
    }
    ctx.closePath();
    for (; i < ends.length; i++) {
      ctx.moveTo(ends[i][0], ends[i][1]);
      i++;
      ctx.lineTo(ends[i][0], ends[i][1]);
    }
  };
  return BoxPath;
}(Path);
function createNormalBox(itemLayout, data, dataIndex, constDim, isInit) {
  var ends = itemLayout.ends;
  var el = new BoxPath({
    shape: {
      points: isInit ? transInit(ends, constDim, itemLayout) : ends
    }
  });
  updateNormalBoxData(itemLayout, el, data, dataIndex, isInit);
  return el;
}
function updateNormalBoxData(itemLayout, el, data, dataIndex, isInit) {
  var seriesModel = data.hostModel;
  var updateMethod = graphic[isInit ? 'initProps' : 'updateProps'];
  updateMethod(el, {
    shape: {
      points: itemLayout.ends
    }
  }, seriesModel, dataIndex);
  el.useStyle(data.getItemVisual(dataIndex, 'style'));
  el.style.strokeNoScale = true;
  el.z2 = 100;
  var itemModel = data.getItemModel(dataIndex);
  var emphasisModel = itemModel.getModel('emphasis');
  setStatesStylesFromModel(el, itemModel);
  toggleHoverEmphasis(el, emphasisModel.get('focus'), emphasisModel.get('blurScope'), emphasisModel.get('disabled'));
}
function transInit(points, dim, itemLayout) {
  return map(points, function (point) {
    point = point.slice();
    point[dim] = itemLayout.initBaseline;
    return point;
  });
}
export default BoxplotView;