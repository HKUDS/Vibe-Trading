
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
import * as graphic from '../../util/graphic.js';
import SymbolClz from './Symbol.js';
import { isObject } from 'zrender/lib/core/util.js';
import { getLabelStatesModels } from '../../label/labelStyle.js';
function symbolNeedsDraw(data, point, idx, opt) {
  return point && !isNaN(point[0]) && !isNaN(point[1]) && !(opt && opt.isIgnore && opt.isIgnore(idx))
  // We do not set clipShape on group, because it will cut part of
  // the symbol element shape. We use the same clip shape here as
  // the line clip.
  && !(opt && opt.clipShape && !opt.clipShape.contain(point[0], point[1])) && data.getItemVisual(idx, 'symbol') !== 'none';
}
function normalizeUpdateOpt(opt) {
  if (opt != null && !isObject(opt)) {
    opt = {
      isIgnore: opt
    };
  }
  return opt || {};
}
function makeSeriesScope(data) {
  var seriesModel = data.hostModel;
  var emphasisModel = seriesModel.getModel('emphasis');
  return {
    emphasisItemStyle: emphasisModel.getModel('itemStyle').getItemStyle(),
    blurItemStyle: seriesModel.getModel(['blur', 'itemStyle']).getItemStyle(),
    selectItemStyle: seriesModel.getModel(['select', 'itemStyle']).getItemStyle(),
    focus: emphasisModel.get('focus'),
    blurScope: emphasisModel.get('blurScope'),
    emphasisDisabled: emphasisModel.get('disabled'),
    hoverScale: emphasisModel.get('scale'),
    labelStatesModels: getLabelStatesModels(seriesModel),
    cursorStyle: seriesModel.get('cursor')
  };
}
function createEl(SymbolCtor, data, newIdx, seriesScope, symbolUpdateOpt, point, group) {
  var symbolEl = new SymbolCtor(data, newIdx, seriesScope, symbolUpdateOpt);
  symbolEl.setPosition(point);
  data.setItemGraphicEl(newIdx, symbolEl);
  group.add(symbolEl);
  return symbolEl;
}
var SymbolDraw = /** @class */function () {
  function SymbolDraw(SymbolCtor) {
    this.group = new graphic.Group();
    this._SymbolCtor = SymbolCtor || SymbolClz;
  }
  /**
   * Update symbols draw by new data
   */
  SymbolDraw.prototype.updateData = function (data, opt) {
    // Remove progressive els.
    this._progressiveEls = null;
    opt = normalizeUpdateOpt(opt);
    var group = this.group;
    var seriesModel = data.hostModel;
    var oldData = this._data;
    var SymbolCtor = this._SymbolCtor;
    var disableAnimation = opt.disableAnimation;
    var seriesScope = this._seriesScope = makeSeriesScope(data);
    var symbolUpdateOpt = {
      disableAnimation: disableAnimation
    };
    var getSymbolPoint = opt.getSymbolPoint || function (idx) {
      return data.getItemLayout(idx);
    };
    // There is no oldLineData only when first rendering or switching from
    // stream mode to normal mode, where previous elements should be removed.
    if (!oldData) {
      group.removeAll();
    }
    data.diff(oldData).add(function (newIdx) {
      var point = getSymbolPoint(newIdx);
      if (symbolNeedsDraw(data, point, newIdx, opt)) {
        createEl(SymbolCtor, data, newIdx, seriesScope, symbolUpdateOpt, point, group);
      }
    }).update(function (newIdx, oldIdx) {
      var symbolEl = oldData.getItemGraphicEl(oldIdx);
      var point = getSymbolPoint(newIdx);
      if (!symbolNeedsDraw(data, point, newIdx, opt)) {
        group.remove(symbolEl);
        return;
      }
      var newSymbolType = data.getItemVisual(newIdx, 'symbol') || 'circle';
      var oldSymbolType = symbolEl && symbolEl.getSymbolType && symbolEl.getSymbolType();
      if (!symbolEl
      // Create a new if symbol type changed.
      || oldSymbolType && oldSymbolType !== newSymbolType) {
        group.remove(symbolEl);
        symbolEl = new SymbolCtor(data, newIdx, seriesScope, symbolUpdateOpt);
        symbolEl.setPosition(point);
      } else {
        symbolEl.updateData(data, newIdx, seriesScope, symbolUpdateOpt);
        var target = {
          x: point[0],
          y: point[1]
        };
        disableAnimation ? symbolEl.attr(target) : graphic.updateProps(symbolEl, target, seriesModel);
      }
      // Add back
      group.add(symbolEl);
      data.setItemGraphicEl(newIdx, symbolEl);
    }).remove(function (oldIdx) {
      var el = oldData.getItemGraphicEl(oldIdx);
      el && el.fadeOut(function () {
        group.remove(el);
      }, seriesModel);
    }).execute();
    this._getSymbolPoint = getSymbolPoint;
    this._data = data;
  };
  ;
  SymbolDraw.prototype.updateLayout = function (opt) {
    var data = this._data;
    if (!data) {
      return;
    }
    var symbolDraw = this;
    var store = data.getStore();
    for (var idx = 0, len = store.count(); idx < len; idx++) {
      var el = data.getItemGraphicEl(idx);
      var point = symbolDraw._getSymbolPoint(idx);
      // FIXME: [FIXME_SYMBOL_CLIP_CONSIDERING_COORD_SYS_ALIGNMENT_DURING_ANIMATION]
      //  See VIEW_COORD_SYS animation (by center/zoom change) and FIXME_VIEW_COORD_SYS_SYNC_BACK.
      //  If we create symbols when roaming them into the clip area, they can not be laid out
      //  based on the intermediate state but can only based on the final state of VIEW_COORD_SYS,
      //  and introduce visual artifacts.
      // Consider clip, need to handle create or remove.
      if (symbolNeedsDraw(data, point, idx, opt)) {
        el = el || createEl(symbolDraw._SymbolCtor, data, idx, symbolDraw._seriesScope, {
          disableAnimation: true
        }, point, symbolDraw.group);
        el.stopAnimation();
        el.setPosition(point);
        el.markRedraw();
      } else if (el) {
        symbolDraw.group.remove(el);
        data.setItemGraphicEl(idx, null);
      }
    }
  };
  ;
  SymbolDraw.prototype.incrementalPrepareUpdate = function (data) {
    this._seriesScope = makeSeriesScope(data);
    this._data = null;
    this.group.removeAll();
  };
  ;
  SymbolDraw.prototype.incrementalUpdate = function (taskParams, data, incrementalId, opt) {
    // Clear
    this._progressiveEls = [];
    opt = normalizeUpdateOpt(opt);
    function updateIncrementalAndHover(el) {
      if (!el.isGroup) {
        el.incremental = incrementalId;
        el.ensureState('emphasis').hoverLayer = graphic.HOVER_LAYER_FOR_INCREMENTAL;
      }
    }
    for (var idx = taskParams.start; idx < taskParams.end; idx++) {
      var point = data.getItemLayout(idx);
      if (symbolNeedsDraw(data, point, idx, opt)) {
        var el = new this._SymbolCtor(data, idx, this._seriesScope);
        el.traverse(updateIncrementalAndHover);
        el.setPosition(point);
        this.group.add(el);
        data.setItemGraphicEl(idx, el);
        this._progressiveEls.push(el);
      }
    }
  };
  ;
  SymbolDraw.prototype.eachRendered = function (cb) {
    graphic.traverseElements(this._progressiveEls || this.group, cb);
  };
  SymbolDraw.prototype.remove = function (enableAnimation) {
    var group = this.group;
    var data = this._data;
    // Incremental model do not have this._data.
    if (data && enableAnimation) {
      data.eachItemGraphicEl(function (el) {
        el.fadeOut(function () {
          group.remove(el);
        }, data.hostModel);
      });
    } else {
      group.removeAll();
    }
  };
  ;
  return SymbolDraw;
}();
export default SymbolDraw;