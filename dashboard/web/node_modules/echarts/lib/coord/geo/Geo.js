
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
import * as zrUtil from 'zrender/lib/core/util.js';
import View, { useLegacyViewCoordSysCenterBase, viewCoordSysCopyViewRect, viewCoordSysSetBoundingRect } from '../View.js';
import geoSourceManager from './geoSourceManager.js';
import { SINGLE_REFERRING } from '../../util/model.js';
import { warn } from '../../util/log.js';
import Transformable from 'zrender/lib/core/Transformable.js';
var GEO_DEFAULT_PARAMS = {
  'geoJSON': {
    aspectScale: 0.75,
    invertLongitute: true
  },
  'geoSVG': {
    aspectScale: 1,
    invertLongitute: false
  }
};
export var geo2DDimensions = ['lng', 'lat'];
var Geo = /** @class */function (_super) {
  __extends(Geo, _super); // See VIEW_COORD_SYS_TRANS_OVERALL_BACKWARD_COMPATIBILITY
  function Geo(name, map, opt) {
    var _this = _super.call(this) || this;
    _this.dimensions = geo2DDimensions;
    _this.type = 'geo';
    // Only store specified name coord via `addGeoCoord`.
    _this._nameCoordMap = zrUtil.createHashMap();
    _this.name = name;
    var projection = opt.projection;
    var source = geoSourceManager.load(map, opt.nameMap, opt.nameProperty);
    var resource = geoSourceManager.getGeoResource(map);
    var resourceType = _this.resourceType = resource ? resource.type : null;
    var regions = _this.regions = source.regions;
    var defaultParams = GEO_DEFAULT_PARAMS[resource.type];
    _this._clip = opt.clip;
    // Not invert longitude if projection exits.
    var invertLongitute = projection ? false : defaultParams.invertLongitute;
    _this.view = new View(invertLongitute, useLegacyViewCoordSysCenterBase(opt.ecModel, opt.api), _this);
    _this.map = map;
    _this._regionsMap = source.regionsMap;
    _this.regions = source.regions;
    if (process.env.NODE_ENV !== 'production' && projection) {
      // Do some check
      if (resourceType === 'geoSVG') {
        if (process.env.NODE_ENV !== 'production') {
          warn("Map " + map + " with SVG source can't use projection. Only GeoJSON source supports projection.");
        }
        projection = null;
      }
      if (!(projection.project && projection.unproject)) {
        if (process.env.NODE_ENV !== 'production') {
          warn('project and unproject must be both provided in the projeciton.');
        }
        projection = null;
      }
    }
    _this.projection = projection;
    var boundingRect;
    if (projection) {
      // Can't reuse the raw bounding rect
      for (var i = 0; i < regions.length; i++) {
        var regionRect = regions[i].getBoundingRect(projection);
        boundingRect = boundingRect || regionRect.clone();
        boundingRect.union(regionRect);
      }
    } else {
      boundingRect = source.boundingRect;
    }
    viewCoordSysSetBoundingRect(_this.view, boundingRect.x, boundingRect.y, boundingRect.width, boundingRect.height);
    // aspectScale and invertLongitute actually is the parameters default raw projection.
    // So we ignore them if projection is given.
    // Ignore default aspect scale if projection exits.
    _this.aspectScale = projection ? 1 : zrUtil.retrieve2(opt.aspectScale, defaultParams.aspectScale);
    return _this;
  }
  Geo.prototype.getRegion = function (name) {
    return this._regionsMap.get(name);
  };
  Geo.prototype.getRegionByCoord = function (coord) {
    var regions = this.regions;
    for (var i = 0; i < regions.length; i++) {
      var region = regions[i];
      if (region.type === 'geoJSON' && region.contain(coord)) {
        return regions[i];
      }
    }
  };
  /**
   * Add geoCoord for indexing by name
   */
  Geo.prototype.addGeoCoord = function (name, geoCoord) {
    this._nameCoordMap.set(name, geoCoord);
  };
  /**
   * Get geoCoord by name
   */
  Geo.prototype.getGeoCoord = function (name) {
    var region = this._regionsMap.get(name);
    // Calculate center only on demand.
    return this._nameCoordMap.get(name) || region && region.getCenter();
  };
  Geo.prototype.dataToPoint = function (data, noRoam, out) {
    if (zrUtil.isString(data)) {
      // Map area name to geoCoord
      data = this.getGeoCoord(data);
    }
    if (data) {
      var projection = this.projection;
      if (projection) {
        // projection may return null point.
        data = projection.project(data);
      }
      return data && this.view.dataToPoint(data, noRoam, out);
    }
  };
  Geo.prototype.pointToData = function (point, reserved, out) {
    var projection = this.projection;
    if (projection) {
      // projection may return null point.
      point = projection.unproject(point);
    }
    // FIXME: if no `point`, should return [NaN, NaN], rather than undefined.
    //  null/undefined has special meaning in `convertFromPixel`.
    return point && this.view.pointToData(point, out);
  };
  Geo.prototype.convertToPixel = function (ecModel, finder, value) {
    var coordSys = getCoordSys(finder);
    return coordSys === this ? coordSys.dataToPoint(value) : null;
  };
  Geo.prototype.convertFromPixel = function (ecModel, finder, pixel) {
    var coordSys = getCoordSys(finder);
    return coordSys === this ? coordSys.pointToData(pixel) : null;
  };
  Geo.prototype.containPoint = function (point) {
    return this.view.containPoint(point);
  };
  Geo.prototype.getArea = function (tolerance) {
    tolerance = tolerance || 0;
    var rect = viewCoordSysCopyViewRect(null, this.view);
    rect.x -= tolerance;
    rect.y -= tolerance;
    rect.width += 2 * tolerance;
    rect.height += 2 * tolerance;
    return rect;
  };
  Geo.prototype.shouldClip = function () {
    return this._clip;
  };
  /**
   * @implements CoordinateSystem['getBoundingRect']
   */
  Geo.prototype.getBoundingRect = function () {
    return this.view.getBoundingRect();
  };
  /**
   * @implements CoordinateSystem['getViewRect']
   */
  Geo.prototype.getViewRect = function () {
    return this.view.getViewRect();
  };
  /**
   * @implements CoordinateSystem['getRoamTransform']
   */
  Geo.prototype.getRoamTransform = function () {
    return this.view.getRoamTransform();
  };
  return Geo;
}(Transformable // See VIEW_COORD_SYS_TRANS_OVERALL_BACKWARD_COMPATIBILITY
);
;
function getCoordSys(finder) {
  var geoModel = finder.geoModel;
  var seriesModel = finder.seriesModel;
  return geoModel ? geoModel.coordinateSystem : seriesModel ? seriesModel.coordinateSystem // For map series.
  || (seriesModel.getReferringComponents('geo', SINGLE_REFERRING).models[0] || {}).coordinateSystem : null;
}
export default Geo;