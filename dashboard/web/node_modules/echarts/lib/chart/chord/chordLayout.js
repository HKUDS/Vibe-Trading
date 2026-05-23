
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
import { normalizeArcAngles } from 'zrender/lib/core/PathProxy.js';
import { SERIES_TYPE_CHORD } from './ChordSeries.js';
import { getCircleLayout } from '../../util/layout.js';
import { createSimpleOverallStageHandler } from '../../util/model.js';
var RADIAN = Math.PI / 180;
export var chordCircularLayoutStageHandler = createSimpleOverallStageHandler(SERIES_TYPE_CHORD, chordCircularLayout);
function chordCircularLayout(ecModel, api) {
  ecModel.eachSeriesByType(SERIES_TYPE_CHORD, function (seriesModel) {
    chordLayout(seriesModel, api);
  });
}
function chordLayout(seriesModel, api) {
  var nodeData = seriesModel.getData();
  var nodeGraph = nodeData.graph;
  var edgeData = seriesModel.getEdgeData();
  var edgeCount = edgeData.count();
  if (!edgeCount) {
    return;
  }
  var _a = getCircleLayout(seriesModel, api),
    cx = _a.cx,
    cy = _a.cy,
    r = _a.r,
    r0 = _a.r0;
  var padAngle = Math.max((seriesModel.get('padAngle') || 0) * RADIAN, 0);
  var minAngle = Math.max((seriesModel.get('minAngle') || 0) * RADIAN, 0);
  var startAngle = -seriesModel.get('startAngle') * RADIAN;
  var endAngle = startAngle + Math.PI * 2;
  var clockwise = seriesModel.get('clockwise');
  var dir = clockwise ? 1 : -1;
  // Normalize angles
  var angles = [startAngle, endAngle];
  normalizeArcAngles(angles, !clockwise);
  var normalizedStartAngle = angles[0],
    normalizedEndAngle = angles[1];
  var totalAngle = normalizedEndAngle - normalizedStartAngle;
  var allZero = nodeData.getSum('value') === 0 && edgeData.getSum('value') === 0;
  // Sum of each node's edge values
  var nodeValues = [];
  var renderedNodeCount = 0;
  nodeGraph.eachEdge(function (edge) {
    // All links use the same value 1 when allZero is true
    var value = allZero ? 1 : edge.getValue('value');
    if (allZero && (value > 0 || minAngle)) {
      // When allZero is true, angle is in direct proportion to number
      // of links both in and out of the node.
      renderedNodeCount += 2;
    }
    var node1Index = edge.node1.dataIndex;
    var node2Index = edge.node2.dataIndex;
    nodeValues[node1Index] = (nodeValues[node1Index] || 0) + value;
    nodeValues[node2Index] = (nodeValues[node2Index] || 0) + value;
  });
  // Update nodeValues with data.value if exists
  var nodeValueSum = 0;
  nodeGraph.eachNode(function (node) {
    var dataValue = node.getValue('value');
    if (!isNaN(dataValue)) {
      nodeValues[node.dataIndex] = Math.max(dataValue, nodeValues[node.dataIndex] || 0);
    }
    if (!allZero && (nodeValues[node.dataIndex] > 0 || minAngle)) {
      // When allZero is false, angle is in direct proportion to node's
      // value
      renderedNodeCount++;
    }
    nodeValueSum += nodeValues[node.dataIndex] || 0;
  });
  if (renderedNodeCount === 0 || nodeValueSum === 0) {
    return;
  }
  if (padAngle * renderedNodeCount >= Math.abs(totalAngle)) {
    // Not enough angle to render the pad, minAngle has higher priority, and padAngle takes the rest
    padAngle = Math.max(0, (Math.abs(totalAngle) - minAngle * renderedNodeCount) / renderedNodeCount);
  }
  if ((padAngle + minAngle) * renderedNodeCount >= Math.abs(totalAngle)) {
    // Not enough angle to render the minAngle, so ignore the minAngle
    minAngle = (Math.abs(totalAngle) - padAngle * renderedNodeCount) / renderedNodeCount;
  }
  var unitAngle = (totalAngle - padAngle * renderedNodeCount * dir) / nodeValueSum;
  var totalDeficit = 0; // sum of deficits of nodes with span < minAngle
  var totalSurplus = 0; // sum of (spans - minAngle) of nodes with span > minAngle
  var totalSurplusSpan = 0; // sum of spans of nodes with span > minAngle
  var minSurplus = Infinity; // min of (spans - minAngle) of nodes with span > minAngle
  nodeGraph.eachNode(function (node) {
    var value = nodeValues[node.dataIndex] || 0;
    var spanAngle = unitAngle * (nodeValueSum ? value : 1) * dir;
    if (Math.abs(spanAngle) < minAngle) {
      totalDeficit += minAngle - Math.abs(spanAngle);
    } else {
      minSurplus = Math.min(minSurplus, Math.abs(spanAngle) - minAngle);
      totalSurplus += Math.abs(spanAngle) - minAngle;
      totalSurplusSpan += Math.abs(spanAngle);
    }
    node.setLayout({
      angle: spanAngle,
      value: value
    });
  });
  var surplusAsMuchAsPossible = false;
  if (totalDeficit > totalSurplus) {
    // Not enough angle to spread the nodes, scale all
    var scale_1 = totalDeficit / totalSurplus;
    nodeGraph.eachNode(function (node) {
      var spanAngle = node.getLayout().angle;
      if (Math.abs(spanAngle) >= minAngle) {
        node.setLayout({
          angle: spanAngle * scale_1,
          ratio: scale_1
        }, true);
      } else {
        node.setLayout({
          angle: minAngle,
          ratio: minAngle === 0 ? 1 : spanAngle / minAngle
        }, true);
      }
    });
  } else {
    // For example, if totalDeficit is 60 degrees and totalSurplus is 70
    // degrees but one of the sector can only reduced by 1 degree,
    // if we decrease it with the ratio of value to other surplused nodes,
    // it will have smaller angle than minAngle itself.
    // So we need to borrow some angle from other nodes.
    nodeGraph.eachNode(function (node) {
      if (surplusAsMuchAsPossible) {
        return;
      }
      var spanAngle = node.getLayout().angle;
      var borrowRatio = Math.min(spanAngle / totalSurplusSpan, 1);
      var borrowAngle = borrowRatio * totalDeficit;
      if (spanAngle - borrowAngle < minAngle) {
        // It will have less than minAngle after borrowing
        surplusAsMuchAsPossible = true;
      }
    });
  }
  var restDeficit = totalDeficit;
  nodeGraph.eachNode(function (node) {
    if (restDeficit <= 0) {
      return;
    }
    var spanAngle = node.getLayout().angle;
    if (spanAngle > minAngle && minAngle > 0) {
      var borrowRatio = surplusAsMuchAsPossible ? 1 : Math.min(spanAngle / totalSurplusSpan, 1);
      var maxBorrowAngle = spanAngle - minAngle;
      var borrowAngle = Math.min(maxBorrowAngle, Math.min(restDeficit, totalDeficit * borrowRatio));
      restDeficit -= borrowAngle;
      node.setLayout({
        angle: spanAngle - borrowAngle,
        ratio: (spanAngle - borrowAngle) / spanAngle
      }, true);
    } else if (minAngle > 0) {
      node.setLayout({
        angle: minAngle,
        ratio: spanAngle === 0 ? 1 : minAngle / spanAngle
      }, true);
    }
  });
  var angle = normalizedStartAngle;
  var edgeAccAngle = [];
  nodeGraph.eachNode(function (node) {
    var spanAngle = Math.max(node.getLayout().angle, minAngle);
    node.setLayout({
      cx: cx,
      cy: cy,
      r0: r0,
      r: r,
      startAngle: angle,
      endAngle: angle + spanAngle * dir,
      clockwise: clockwise
    }, true);
    edgeAccAngle[node.dataIndex] = angle;
    angle += (spanAngle + padAngle) * dir;
  });
  nodeGraph.eachEdge(function (edge) {
    var value = allZero ? 1 : edge.getValue('value');
    var spanAngle = unitAngle * (nodeValueSum ? value : 1) * dir;
    var node1Index = edge.node1.dataIndex;
    var sStartAngle = edgeAccAngle[node1Index] || 0;
    var sSpan = Math.abs((edge.node1.getLayout().ratio || 1) * spanAngle);
    var sEndAngle = sStartAngle + sSpan * dir;
    var s1 = [cx + r0 * Math.cos(sStartAngle), cy + r0 * Math.sin(sStartAngle)];
    var s2 = [cx + r0 * Math.cos(sEndAngle), cy + r0 * Math.sin(sEndAngle)];
    var node2Index = edge.node2.dataIndex;
    var tStartAngle = edgeAccAngle[node2Index] || 0;
    var tSpan = Math.abs((edge.node2.getLayout().ratio || 1) * spanAngle);
    var tEndAngle = tStartAngle + tSpan * dir;
    var t1 = [cx + r0 * Math.cos(tStartAngle), cy + r0 * Math.sin(tStartAngle)];
    var t2 = [cx + r0 * Math.cos(tEndAngle), cy + r0 * Math.sin(tEndAngle)];
    edge.setLayout({
      s1: s1,
      s2: s2,
      sStartAngle: sStartAngle,
      sEndAngle: sEndAngle,
      t1: t1,
      t2: t2,
      tStartAngle: tStartAngle,
      tEndAngle: tEndAngle,
      cx: cx,
      cy: cy,
      r: r0,
      value: value,
      clockwise: clockwise
    });
    edgeAccAngle[node1Index] = sEndAngle;
    edgeAccAngle[node2Index] = tEndAngle;
  });
}