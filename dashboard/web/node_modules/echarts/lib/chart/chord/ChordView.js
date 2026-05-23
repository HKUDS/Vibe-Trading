
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
import * as graphic from '../../util/graphic.js';
import ChartView from '../../view/Chart.js';
import { SERIES_TYPE_CHORD } from './ChordSeries.js';
import ChordPiece from './ChordPiece.js';
import { ChordEdge } from './ChordEdge.js';
import { parsePercent } from '../../util/number.js';
import { getECData } from '../../util/innerStore.js';
var RADIAN = Math.PI / 180;
var ChordView = /** @class */function (_super) {
  __extends(ChordView, _super);
  function ChordView() {
    var _this = _super !== null && _super.apply(this, arguments) || this;
    _this.type = SERIES_TYPE_CHORD;
    return _this;
  }
  ChordView.prototype.init = function (ecModel, api) {};
  ChordView.prototype.render = function (seriesModel, ecModel, api) {
    var data = seriesModel.getData();
    var oldData = this._data;
    var group = this.group;
    var startAngle = -seriesModel.get('startAngle') * RADIAN;
    data.diff(oldData).add(function (newIdx) {
      /* Consider the case when there are only two nodes A and B,
       * and there is a link between A and B.
       * At first, they are both disselected from legend. And then
       * when A is selected, A will go into `add` method. But since
       * there are no edges to be displayed, A should not be added.
       * So we should only add A when layout is defined.
       */
      var layout = data.getItemLayout(newIdx);
      if (layout) {
        var el = new ChordPiece(data, newIdx, startAngle);
        getECData(el).dataIndex = newIdx;
        group.add(el);
      }
    }).update(function (newIdx, oldIdx) {
      var el = oldData.getItemGraphicEl(oldIdx);
      var layout = data.getItemLayout(newIdx);
      /* Consider the case when there are only two nodes A and B,
       * and there is a link between A and B.
       * and when A is disselected from legend, there should be
       * nothing to display. But in the `data.diff` method, B will go
       * into `update` method and having no layout.
       * In this case, we need to remove B.
       */
      if (!layout) {
        el && graphic.removeElementWithFadeOut(el, seriesModel, oldIdx);
        return;
      }
      if (!el) {
        el = new ChordPiece(data, newIdx, startAngle);
      } else {
        el.updateData(data, newIdx, startAngle);
      }
      group.add(el);
    }).remove(function (oldIdx) {
      var el = oldData.getItemGraphicEl(oldIdx);
      el && graphic.removeElementWithFadeOut(el, seriesModel, oldIdx);
    }).execute();
    if (!oldData) {
      var center = seriesModel.get('center');
      this.group.scaleX = 0.01;
      this.group.scaleY = 0.01;
      this.group.originX = parsePercent(center[0], api.getWidth());
      this.group.originY = parsePercent(center[1], api.getHeight());
      graphic.initProps(this.group, {
        scaleX: 1,
        scaleY: 1
      }, seriesModel);
    }
    this._data = data;
    this.renderEdges(seriesModel, startAngle);
  };
  ChordView.prototype.renderEdges = function (seriesModel, startAngle) {
    var nodeData = seriesModel.getData();
    var edgeData = seriesModel.getEdgeData();
    var oldData = this._edgeData;
    var group = this.group;
    edgeData.diff(oldData).add(function (newIdx) {
      var el = new ChordEdge(nodeData, edgeData, newIdx, startAngle);
      getECData(el).dataIndex = newIdx;
      group.add(el);
    }).update(function (newIdx, oldIdx) {
      var el = oldData.getItemGraphicEl(oldIdx);
      el.updateData(nodeData, edgeData, newIdx, startAngle);
      group.add(el);
    }).remove(function (oldIdx) {
      var el = oldData.getItemGraphicEl(oldIdx);
      el && graphic.removeElementWithFadeOut(el, seriesModel, oldIdx);
    }).execute();
    this._edgeData = edgeData;
  };
  ChordView.prototype.dispose = function () {};
  ChordView.type = SERIES_TYPE_CHORD;
  return ChordView;
}(ChartView);
export default ChordView;