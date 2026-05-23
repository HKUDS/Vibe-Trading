
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
import { extend, isString } from 'zrender/lib/core/util.js';
import * as graphic from '../../util/graphic.js';
import { getSectorCornerRadius } from '../helper/sectorHelper.js';
import { saveOldStyle } from '../../animation/basicTransition.js';
import { setStatesStylesFromModel, toggleHoverEmphasis } from '../../util/states.js';
import { getECData } from '../../util/innerStore.js';
var ChordPathShape = /** @class */function () {
  function ChordPathShape() {
    // Souce node, two points forming an arc
    this.s1 = [0, 0];
    this.s2 = [0, 0];
    this.sStartAngle = 0;
    this.sEndAngle = 0;
    // Target node, two points forming an arc
    this.t1 = [0, 0];
    this.t2 = [0, 0];
    this.tStartAngle = 0;
    this.tEndAngle = 0;
    this.cx = 0;
    this.cy = 0;
    // series.r0 of ChordSeries
    this.r = 0;
    this.clockwise = true;
  }
  return ChordPathShape;
}();
export { ChordPathShape };
var ChordEdge = /** @class */function (_super) {
  __extends(ChordEdge, _super);
  function ChordEdge(nodeData, edgeData, edgeIdx, startAngle) {
    var _this = _super.call(this) || this;
    getECData(_this).dataType = 'edge';
    _this.updateData(nodeData, edgeData, edgeIdx, startAngle, true);
    return _this;
  }
  ChordEdge.prototype.buildPath = function (ctx, shape) {
    // Start from n11
    ctx.moveTo(shape.s1[0], shape.s1[1]);
    var ratio = 0.7;
    var clockwise = shape.clockwise;
    // Draw the arc from n11 to n12
    ctx.arc(shape.cx, shape.cy, shape.r, shape.sStartAngle, shape.sEndAngle, !clockwise);
    // Bezier curve to cp1 and then to n21
    ctx.bezierCurveTo((shape.cx - shape.s2[0]) * ratio + shape.s2[0], (shape.cy - shape.s2[1]) * ratio + shape.s2[1], (shape.cx - shape.t1[0]) * ratio + shape.t1[0], (shape.cy - shape.t1[1]) * ratio + shape.t1[1], shape.t1[0], shape.t1[1]);
    // Draw the arc from n21 to n22
    ctx.arc(shape.cx, shape.cy, shape.r, shape.tStartAngle, shape.tEndAngle, !clockwise);
    // Bezier curve back to cp2 and then to n11
    ctx.bezierCurveTo((shape.cx - shape.t2[0]) * ratio + shape.t2[0], (shape.cy - shape.t2[1]) * ratio + shape.t2[1], (shape.cx - shape.s1[0]) * ratio + shape.s1[0], (shape.cy - shape.s1[1]) * ratio + shape.s1[1], shape.s1[0], shape.s1[1]);
    ctx.closePath();
  };
  ChordEdge.prototype.updateData = function (nodeData, edgeData, edgeIdx, startAngle, firstCreate) {
    var seriesModel = nodeData.hostModel;
    var edge = edgeData.graph.getEdgeByIndex(edgeIdx);
    var layout = edge.getLayout();
    var itemModel = edge.node1.getModel();
    var edgeModel = edgeData.getItemModel(edge.dataIndex);
    var lineStyle = edgeModel.getModel('lineStyle');
    var emphasisModel = edgeModel.getModel('emphasis');
    var focus = emphasisModel.get('focus');
    var shape = extend(getSectorCornerRadius(itemModel.getModel('itemStyle'), layout, true), layout);
    var el = this;
    // Ignore NaN data.
    if (isNaN(shape.sStartAngle) || isNaN(shape.tStartAngle)) {
      // Use NaN shape to avoid drawing shape.
      el.setShape(shape);
      return;
    }
    if (firstCreate) {
      el.setShape(shape);
      applyEdgeFill(el, edge, nodeData, lineStyle);
    } else {
      saveOldStyle(el);
      applyEdgeFill(el, edge, nodeData, lineStyle);
      graphic.updateProps(el, {
        shape: shape
      }, seriesModel, edgeIdx);
    }
    toggleHoverEmphasis(this, focus === 'adjacency' ? edge.getAdjacentDataIndices() : focus, emphasisModel.get('blurScope'), emphasisModel.get('disabled'));
    setStatesStylesFromModel(el, edgeModel, 'lineStyle');
    edgeData.setItemGraphicEl(edge.dataIndex, el);
  };
  return ChordEdge;
}(graphic.Path);
export { ChordEdge };
function applyEdgeFill(edgeShape, edge, nodeData, lineStyleModel) {
  var node1 = edge.node1;
  var node2 = edge.node2;
  var edgeStyle = edgeShape.style;
  edgeShape.setStyle(lineStyleModel.getLineStyle());
  var color = lineStyleModel.get('color');
  switch (color) {
    case 'source':
      // TODO: use visual and node1.getVisual('color');
      edgeStyle.fill = nodeData.getItemVisual(node1.dataIndex, 'style').fill;
      edgeStyle.decal = node1.getVisual('style').decal;
      break;
    case 'target':
      edgeStyle.fill = nodeData.getItemVisual(node2.dataIndex, 'style').fill;
      edgeStyle.decal = node2.getVisual('style').decal;
      break;
    case 'gradient':
      var sourceColor = nodeData.getItemVisual(node1.dataIndex, 'style').fill;
      var targetColor = nodeData.getItemVisual(node2.dataIndex, 'style').fill;
      if (isString(sourceColor) && isString(targetColor)) {
        // Gradient direction is perpendicular to the mid-angles
        // of source and target nodes.
        var shape = edgeShape.shape;
        var sMidX = (shape.s1[0] + shape.s2[0]) / 2;
        var sMidY = (shape.s1[1] + shape.s2[1]) / 2;
        var tMidX = (shape.t1[0] + shape.t2[0]) / 2;
        var tMidY = (shape.t1[1] + shape.t2[1]) / 2;
        edgeStyle.fill = new graphic.LinearGradient(sMidX, sMidY, tMidX, tMidY, [{
          offset: 0,
          color: sourceColor
        }, {
          offset: 1,
          color: targetColor
        }], true);
      }
      break;
  }
}