#################################################################################
# The Institute for the Design of Advanced Energy Systems Integrated Platform
# Framework (IDAES IP) was produced under the DOE Institute for the
# Design of Advanced Energy Systems (IDAES).
#
# Copyright (c) 2018-2024 by the software owners: The Regents of the
# University of California, through Lawrence Berkeley National Laboratory,
# National Technology & Engineering Solutions of Sandia, LLC, Carnegie Mellon
# University, West Virginia University Research Corporation, et al.
# All rights reserved.  Please see the files COPYRIGHT.md and LICENSE.md
# for full copyright and license information.
#################################################################################
"""
Tests for common methods used by generic framework

Author: A Lee
"""
import pytest
from types import MethodType

from pyomo.environ import Block, ConcreteModel, units as pyunits, Var
from pyomo.common.config import ConfigBlock, ConfigValue

from idaes.core import declare_process_block_class
from idaes.core import Component, LiquidPhase, SolidPhase, VaporPhase, PhaseType as PT
from idaes.models.properties.modular_properties.base.utility import (
    GenericPropertyPackageError,
    get_method,
    get_phase_method,
    get_component_object,
    get_bounds_from_config,
    get_concentration_term,
    ConcentrationForm,
    identify_VL_component_list,
    estimate_Pbub,
    estimate_Pdew,
    estimate_Tbub,
    estimate_Tdew,
)
from idaes.models.properties.modular_properties.base.generic_property import (
    GenericParameterData,
)
from idaes.models.properties.modular_properties.base.generic_reaction import rxn_config
from idaes.core.util.exceptions import ConfigurationError, PropertyPackageError
from idaes.core.util.misc import add_object_reference
from idaes.models.properties.modular_properties.base.tests.dummy_eos import DummyEoS
from idaes.models.properties.modular_properties.phase_equil.henry import (
    ConstantH,
    HenryType,
)
from idaes.models.properties.modular_properties.eos.ceos import Cubic, CubicType
from idaes.models.properties.modular_properties.phase_equil import SmoothVLE
from idaes.models.properties.modular_properties.phase_equil.bubble_dew import (
    LogBubbleDew,
)
from idaes.models.properties.modular_properties.phase_equil.forms import log_fugacity
from idaes.models.properties.modular_properties.pure import NIST
from idaes.models.properties.modular_properties.state_definitions import FTPx


@pytest.fixture
def frame():
    m = Block(concrete=True)
    m.params = Block()
    m.params.config = ConfigBlock()
    m.params.config.declare("test_arg", ConfigValue())
    m.params.config.declare("state_bounds", ConfigValue())

    def get_component(self, comp):
        return getattr(self, comp)

    m.params.get_component = MethodType(get_component, m.params)
    m.params.get_phase = MethodType(get_component, m.params)

    m.params.comp = Block()
    m.params.comp.config = ConfigBlock()
    m.params.comp.config.declare("test_arg_2", ConfigValue())

    return m


@pytest.mark.unit
def test_generic_property_package_error():
    with pytest.raises(
        PropertyPackageError,
        match="Generic Property Package instance block called for "
        "prop, but was not provided with a method "
        "for this property. Please add a method for this property "
        "in the property parameter configuration.",
    ):
        raise GenericPropertyPackageError("block", "prop")


@pytest.mark.unit
def test_get_component_object(frame):
    assert get_component_object(frame, "comp") is frame.params.comp


class TestGetMethod:
    @pytest.mark.unit
    def test_get_method_invalid_name(self, frame):
        with pytest.raises(
            AttributeError,
            match="ScalarBlock Generic Property Package called for "
            "invalid configuration option foo. Please contact the "
            "developer of the property package.",
        ):
            get_method(frame, "foo")

    @pytest.mark.unit
    def test_get_method_none(self, frame):
        with pytest.raises(
            GenericPropertyPackageError,
            match="Generic Property Package instance ScalarBlock "
            "called for test_arg, but was not provided with a "
            "method for this property. Please add a method for "
            "this property in the property parameter "
            "configuration.",
        ):
            get_method(frame, "test_arg")

    @pytest.mark.unit
    def test_get_method_not_callable(self, frame):
        frame.params.config.test_arg = "foo"
        with pytest.raises(
            ConfigurationError,
            match="ScalarBlock Generic Property Package received "
            "invalid value for argument test_arg. Value must be a "
            "method, a class with a method named expression or a "
            "module containing one of the previous.",
        ):
            get_method(frame, "test_arg")

    @pytest.mark.unit
    def test_get_method_simple(self, frame):
        def test_arg():
            return "bar"

        frame.params.config.test_arg = test_arg

        mthd = get_method(frame, "test_arg")
        assert mthd() == "bar"

    @pytest.mark.unit
    def test_get_method_class_w_method(self, frame):
        class TestClass:
            def test_arg():
                return "bar"

        frame.params.config.test_arg = TestClass

        mthd = get_method(frame, "test_arg")
        assert mthd() == "bar"

    @pytest.mark.unit
    def test_get_method_class_w_return_expression(self, frame):
        class TestClass:
            def return_expression(*args, **kwargs):
                return "bar"

        frame.params.config.test_arg = TestClass

        mthd = get_method(frame, "test_arg")
        assert mthd() == "bar"

    @pytest.mark.unit
    def test_get_method_phase(self, frame):
        def test_arg():
            return "bar"

        frame.params.config.test_arg = {"test_phase": test_arg}

        mthd = get_method(frame, "test_arg", phase="test_phase")
        assert mthd() == "bar"

    @pytest.mark.unit
    def test_get_method_comp(self, frame):
        def test_arg():
            return "bar"

        frame.params.comp.config.test_arg_2 = test_arg

        mthd = get_method(frame, "test_arg_2", comp="comp")
        assert mthd() == "bar"

    @pytest.mark.unit
    def test_get_method_phase_comp(self, frame):
        def test_arg():
            return "bar"

        frame.params.comp.config.test_arg_2 = {"test_phase": test_arg}

        mthd = get_method(frame, "test_arg_2", comp="comp", phase="test_phase")
        assert mthd() == "bar"


class TestGetPhaseMethod:
    @pytest.mark.unit
    def test_get_phase_method_invalid_name(self, frame):
        with pytest.raises(
            AttributeError,
            match="ScalarBlock Generic Property Package called for "
            "invalid configuration option foo. Please contact the "
            "developer of the property package.",
        ):
            get_phase_method(frame, "foo", "comp")

    @pytest.mark.unit
    def test_get_phase_method_none(self, frame):
        with pytest.raises(
            GenericPropertyPackageError,
            match="Generic Property Package instance ScalarBlock "
            "called for test_arg_2, but was not provided with a "
            "method for this property. Please add a method for "
            "this property in the property parameter "
            "configuration.",
        ):
            get_phase_method(frame, "test_arg_2", "comp")

    @pytest.mark.unit
    def test_get_phase_method_not_callable(self, frame):
        frame.params.comp.config.test_arg_2 = "foo"
        with pytest.raises(
            ConfigurationError,
            match="ScalarBlock Generic Property Package received "
            "invalid value for argument test_arg_2. Value must be a "
            "method, a class with a method named expression or a "
            "module containing one of the previous.",
        ):
            get_phase_method(frame, "test_arg_2", "comp")

    @pytest.mark.unit
    def test_get_phase_method_simple(self, frame):
        def test_arg():
            return "bar"

        frame.params.comp.config.test_arg_2 = test_arg

        mthd = get_phase_method(frame, "test_arg_2", "comp")
        assert mthd() == "bar"

    @pytest.mark.unit
    def test_get_phase_method_class_w_method(self, frame):
        class TestClass:
            def test_arg_2():
                return "bar"

        frame.params.comp.config.test_arg_2 = TestClass

        mthd = get_phase_method(frame, "test_arg_2", "comp")
        assert mthd() == "bar"

    @pytest.mark.unit
    def test_get_phase_method_class_w_return_expression(self, frame):
        class TestClass:
            def return_expression():
                return "bar"

        frame.params.comp.config.test_arg_2 = TestClass

        mthd = get_phase_method(frame, "test_arg_2", "comp")
        assert mthd() == "bar"


class TestGetBoundsFromConfig:
    @pytest.mark.unit
    def test_no_state_bounds(self, frame):
        bounds, value = get_bounds_from_config(frame, "foo", "bar")

        assert bounds == (None, None)
        assert value is None

    @pytest.mark.unit
    def test_no_state_bounds_3(self, frame):
        frame.params.config.state_bounds = {"test_state": (1, 2, 3)}
        bounds, value = get_bounds_from_config(frame, "test_state", "bar")

        assert bounds == (1, 3)
        assert value == 2

    @pytest.mark.unit
    def test_no_state_bounds_4(self, frame):
        frame.params.config.state_bounds = {"test_state": (1, 2, 3, pyunits.km)}
        bounds, value = get_bounds_from_config(frame, "test_state", pyunits.m)

        assert bounds == (1000, 3000)
        assert value == 2000


class TestGetConcentrationTerm:
    @pytest.fixture
    def frame(self):
        m = Block(concrete=True)

        m.params = Block()

        m.params.config = ConfigBlock()

        m.params.config.declare(
            "rate_reactions", ConfigBlock(implicit=True, implicit_domain=rxn_config)
        )
        m.params.config.declare(
            "equilibrium_reactions",
            ConfigBlock(implicit=True, implicit_domain=rxn_config),
        )
        m.params.config.declare(
            "inherent_reactions", ConfigBlock(implicit=True, implicit_domain=rxn_config)
        )

        add_object_reference(m, "state_ref", m)

        m.conc_mol_phase_comp = Var()
        m.act_phase_comp = Var()
        m.molality_phase_comp = Var()
        m.mole_frac_phase_comp = Var()
        m.mass_frac_phase_comp = Var()
        m.pressure_phase_comp = Var()

        m.log_conc_mol_phase_comp = Var()
        m.log_act_phase_comp = Var()
        m.log_molality_phase_comp = Var()
        m.log_mole_frac_phase_comp = Var()
        m.log_mass_frac_phase_comp = Var()
        m.log_pressure_phase_comp = Var()

        return m

    @pytest.mark.unit
    def test_rate_molarity(self, frame):
        frame.params.config.rate_reactions["r1"] = rxn_config
        frame.params.config.rate_reactions["r1"].concentration_form = (
            ConcentrationForm.molarity
        )

        assert get_concentration_term(frame, "r1") is frame.conc_mol_phase_comp
        assert (
            get_concentration_term(frame, "r1", log=True)
            is frame.log_conc_mol_phase_comp
        )

    @pytest.mark.unit
    def test_rate_activity(self, frame):
        frame.params.config.rate_reactions["r1"] = rxn_config
        frame.params.config.rate_reactions["r1"].concentration_form = (
            ConcentrationForm.activity
        )

        assert get_concentration_term(frame, "r1") is frame.act_phase_comp
        assert get_concentration_term(frame, "r1", log=True) is frame.log_act_phase_comp

    @pytest.mark.unit
    def test_rate_molality(self, frame):
        frame.params.config.rate_reactions["r1"] = rxn_config
        frame.params.config.rate_reactions["r1"].concentration_form = (
            ConcentrationForm.molality
        )

        assert get_concentration_term(frame, "r1") is frame.molality_phase_comp
        assert (
            get_concentration_term(frame, "r1", log=True)
            is frame.log_molality_phase_comp
        )

    @pytest.mark.unit
    def test_rate_mole_frac(self, frame):
        frame.params.config.rate_reactions["r1"] = rxn_config
        frame.params.config.rate_reactions["r1"].concentration_form = (
            ConcentrationForm.moleFraction
        )

        assert get_concentration_term(frame, "r1") is frame.mole_frac_phase_comp
        assert (
            get_concentration_term(frame, "r1", log=True)
            is frame.log_mole_frac_phase_comp
        )

    @pytest.mark.unit
    def test_rate_mass_frac(self, frame):
        frame.params.config.rate_reactions["r1"] = rxn_config
        frame.params.config.rate_reactions["r1"].concentration_form = (
            ConcentrationForm.massFraction
        )

        assert get_concentration_term(frame, "r1") is frame.mass_frac_phase_comp
        assert (
            get_concentration_term(frame, "r1", log=True)
            is frame.log_mass_frac_phase_comp
        )

    @pytest.mark.unit
    def test_rate_partial_pressure(self, frame):
        frame.params.config.rate_reactions["r1"] = rxn_config
        frame.params.config.rate_reactions["r1"].concentration_form = (
            ConcentrationForm.partialPressure
        )

        assert get_concentration_term(frame, "r1") is frame.pressure_phase_comp
        assert (
            get_concentration_term(frame, "r1", log=True)
            is frame.log_pressure_phase_comp
        )

    @pytest.mark.unit
    def test_equilibrium_molarity(self, frame):
        frame.params.config.equilibrium_reactions["e1"] = rxn_config
        frame.params.config.equilibrium_reactions["e1"].concentration_form = (
            ConcentrationForm.molarity
        )

        assert get_concentration_term(frame, "e1") is frame.conc_mol_phase_comp
        assert (
            get_concentration_term(frame, "e1", log=True)
            is frame.log_conc_mol_phase_comp
        )

    @pytest.mark.unit
    def test_equilibrium_activity(self, frame):
        frame.params.config.equilibrium_reactions["e1"] = rxn_config
        frame.params.config.equilibrium_reactions["e1"].concentration_form = (
            ConcentrationForm.activity
        )

        assert get_concentration_term(frame, "e1") is frame.act_phase_comp
        assert get_concentration_term(frame, "e1", log=True) is frame.log_act_phase_comp

    @pytest.mark.unit
    def test_equilibrium_molality(self, frame):
        frame.params.config.equilibrium_reactions["e1"] = rxn_config
        frame.params.config.equilibrium_reactions["e1"].concentration_form = (
            ConcentrationForm.molality
        )

        assert get_concentration_term(frame, "e1") is frame.molality_phase_comp
        assert (
            get_concentration_term(frame, "e1", log=True)
            is frame.log_molality_phase_comp
        )

    @pytest.mark.unit
    def test_equilibrium_mole_frac(self, frame):
        frame.params.config.equilibrium_reactions["e1"] = rxn_config
        frame.params.config.equilibrium_reactions["e1"].concentration_form = (
            ConcentrationForm.moleFraction
        )

        assert get_concentration_term(frame, "e1") is frame.mole_frac_phase_comp
        assert (
            get_concentration_term(frame, "e1", log=True)
            is frame.log_mole_frac_phase_comp
        )

    @pytest.mark.unit
    def test_equilibrium_mass_frac(self, frame):
        frame.params.config.equilibrium_reactions["e1"] = rxn_config
        frame.params.config.equilibrium_reactions["e1"].concentration_form = (
            ConcentrationForm.massFraction
        )

        assert get_concentration_term(frame, "e1") is frame.mass_frac_phase_comp
        assert (
            get_concentration_term(frame, "e1", log=True)
            is frame.log_mass_frac_phase_comp
        )

    @pytest.mark.unit
    def test_equilibrium_partial_pressure(self, frame):
        frame.params.config.equilibrium_reactions["e1"] = rxn_config
        frame.params.config.equilibrium_reactions["e1"].concentration_form = (
            ConcentrationForm.partialPressure
        )

        assert get_concentration_term(frame, "e1") is frame.pressure_phase_comp
        assert (
            get_concentration_term(frame, "e1", log=True)
            is frame.log_pressure_phase_comp
        )

    @pytest.fixture
    def frame2(self):
        m = Block(concrete=True)

        m.params = Block()

        m.params.config = ConfigBlock()

        m.params.config.declare(
            "inherent_reactions", ConfigBlock(implicit=True, implicit_domain=rxn_config)
        )

        add_object_reference(m, "state_ref", m)

        m.conc_mol_phase_comp = Var()
        m.act_phase_comp = Var()
        m.molality_phase_comp = Var()
        m.mole_frac_phase_comp = Var()
        m.mass_frac_phase_comp = Var()
        m.pressure_phase_comp = Var()

        m.log_conc_mol_phase_comp = Var()
        m.log_act_phase_comp = Var()
        m.log_molality_phase_comp = Var()
        m.log_mole_frac_phase_comp = Var()
        m.log_mass_frac_phase_comp = Var()
        m.log_pressure_phase_comp = Var()

        return m

    @pytest.mark.unit
    def test_inherent_molarity(self, frame2):
        frame2.params.config.inherent_reactions["i1"] = rxn_config
        frame2.params.config.inherent_reactions["i1"].concentration_form = (
            ConcentrationForm.molarity
        )

        assert get_concentration_term(frame2, "i1") is frame2.conc_mol_phase_comp
        assert (
            get_concentration_term(frame2, "i1", log=True)
            is frame2.log_conc_mol_phase_comp
        )

    @pytest.mark.unit
    def test_inherent_activity(self, frame2):
        frame2.params.config.inherent_reactions["i1"] = rxn_config
        frame2.params.config.inherent_reactions["i1"].concentration_form = (
            ConcentrationForm.activity
        )

        assert get_concentration_term(frame2, "i1") is frame2.act_phase_comp
        assert (
            get_concentration_term(frame2, "i1", log=True) is frame2.log_act_phase_comp
        )

    @pytest.mark.unit
    def test_inherent_molality(self, frame2):
        frame2.params.config.inherent_reactions["i1"] = rxn_config
        frame2.params.config.inherent_reactions["i1"].concentration_form = (
            ConcentrationForm.molality
        )

        assert get_concentration_term(frame2, "i1") is frame2.molality_phase_comp
        assert (
            get_concentration_term(frame2, "i1", log=True)
            is frame2.log_molality_phase_comp
        )

    @pytest.mark.unit
    def test_inherent_mole_frac(self, frame2):
        frame2.params.config.inherent_reactions["i1"] = rxn_config
        frame2.params.config.inherent_reactions["i1"].concentration_form = (
            ConcentrationForm.moleFraction
        )

        assert get_concentration_term(frame2, "i1") is frame2.mole_frac_phase_comp
        assert (
            get_concentration_term(frame2, "i1", log=True)
            is frame2.log_mole_frac_phase_comp
        )

    @pytest.mark.unit
    def test_inherent_mass_frac(self, frame2):
        frame2.params.config.inherent_reactions["i1"] = rxn_config
        frame2.params.config.inherent_reactions["i1"].concentration_form = (
            ConcentrationForm.massFraction
        )

        assert get_concentration_term(frame2, "i1") is frame2.mass_frac_phase_comp
        assert (
            get_concentration_term(frame2, "i1", log=True)
            is frame2.log_mass_frac_phase_comp
        )

    @pytest.mark.unit
    def test_inherent_partial_pressure(self, frame2):
        frame2.params.config.inherent_reactions["i1"] = rxn_config
        frame2.params.config.inherent_reactions["i1"].concentration_form = (
            ConcentrationForm.partialPressure
        )

        assert get_concentration_term(frame2, "i1") is frame2.pressure_phase_comp
        assert (
            get_concentration_term(frame2, "i1", log=True)
            is frame2.log_pressure_phase_comp
        )


class TestIdentifyVLComponentList:
    # Declare a base units dict to save code later
    base_units = {
        "time": pyunits.s,
        "length": pyunits.m,
        "mass": pyunits.kg,
        "amount": pyunits.mol,
        "temperature": pyunits.K,
    }

    # Dummy methods for properties
    def set_metadata(self, b):
        pass

    def define_state(self, b):
        pass

    @declare_process_block_class("DummyParameterBlock")
    class DummyParameterData(GenericParameterData):
        def configure(self):
            self.configured = True

    @pytest.fixture()
    def frame(self):
        m = ConcreteModel()
        m.params = DummyParameterBlock(
            components={
                "a": {},
                "b": {},
                "c": {},
            },
            phases={
                "p1": {
                    "type": LiquidPhase,
                    "equation_of_state": DummyEoS,
                },
                "p2": {
                    "type": VaporPhase,
                    "equation_of_state": DummyEoS,
                },
                "p3": {
                    "type": SolidPhase,
                    "equation_of_state": DummyEoS,
                },
            },
            state_definition=self,
            pressure_ref=100000.0,
            temperature_ref=300,
            base_units=self.base_units,
        )

        m.props = m.params.build_state_block([1], defined_state=False)

        return m

    @pytest.mark.unit
    def test_invalid_VL_pair(self, frame):
        with pytest.raises(
            PropertyPackageError,
            match="Phase pair p1-p3 was identified as being a VLE pair, "
            "however p1 is liquid but p3 is not vapor.",
        ):
            identify_VL_component_list(frame.props[1], ("p1", "p3"))

        with pytest.raises(
            PropertyPackageError,
            match="Phase pair p2-p3 was identified as being a VLE pair, "
            "however neither p2 nor p3 is liquid.",
        ):
            identify_VL_component_list(frame.props[1], ("p2", "p3"))

    @pytest.mark.unit
    def test_all_components(self, frame):
        l_phase, v_phase, vl_comps, henry_comps, l_only_comps, v_only_comps = (
            identify_VL_component_list(frame.props[1], ("p1", "p2"))
        )

        assert l_phase == "p1"
        assert v_phase == "p2"
        assert vl_comps == ["a", "b", "c"]
        assert henry_comps == []
        assert l_only_comps == []
        assert v_only_comps == []

    @pytest.mark.unit
    def test_all_types_components(self):
        m = ConcreteModel()
        m.params = DummyParameterBlock(
            components={
                "a": {},
                "b": {
                    "valid_phase_types": PT.liquidPhase,
                },
                "c": {
                    "valid_phase_types": PT.vaporPhase,
                },
                "d": {
                    "valid_phase_types": PT.solidPhase,
                },
                "e": {
                    "parameter_data": {"henry_ref": {"p1": 86}},
                    "henry_component": {
                        "p1": {"method": ConstantH, "type": HenryType.Kpx}
                    },
                },
            },
            phases={
                "p1": {
                    "type": LiquidPhase,
                    "equation_of_state": DummyEoS,
                },
                "p2": {
                    "type": VaporPhase,
                    "equation_of_state": DummyEoS,
                },
                "p3": {
                    "type": SolidPhase,
                    "equation_of_state": DummyEoS,
                },
            },
            state_definition=self,
            pressure_ref=100000.0,
            temperature_ref=300,
            base_units=self.base_units,
        )

        m.props = m.params.build_state_block([1], defined_state=False)
        l_phase, v_phase, vl_comps, henry_comps, l_only_comps, v_only_comps = (
            identify_VL_component_list(m.props[1], ("p1", "p2"))
        )
        assert l_phase == "p1"
        assert v_phase == "p2"
        assert vl_comps == ["a"]
        assert henry_comps == ["e"]
        assert l_only_comps == ["b"]
        assert v_only_comps == ["c"]

    @pytest.mark.unit
    def test_henry_components_only(self):
        m = ConcreteModel()
        m.params = DummyParameterBlock(
            components={
                "b": {
                    "valid_phase_types": PT.liquidPhase,
                },
                "c": {
                    "valid_phase_types": PT.vaporPhase,
                },
                "d": {
                    "valid_phase_types": PT.solidPhase,
                },
                "e": {
                    "parameter_data": {"henry_ref": {"p1": 86}},
                    "henry_component": {
                        "p1": {"method": ConstantH, "type": HenryType.Kpx}
                    },
                },
            },
            phases={
                "p1": {
                    "type": LiquidPhase,
                    "equation_of_state": DummyEoS,
                },
                "p2": {
                    "type": VaporPhase,
                    "equation_of_state": DummyEoS,
                },
                "p3": {
                    "type": SolidPhase,
                    "equation_of_state": DummyEoS,
                },
            },
            state_definition=self,
            pressure_ref=100000.0,
            temperature_ref=300,
            base_units=self.base_units,
        )

        m.props = m.params.build_state_block([1], defined_state=False)
        l_phase, v_phase, vl_comps, henry_comps, l_only_comps, v_only_comps = (
            identify_VL_component_list(m.props[1], ("p1", "p2"))
        )
        assert l_phase == "p1"
        assert v_phase == "p2"
        assert vl_comps == []
        assert henry_comps == ["e"]
        assert l_only_comps == ["b"]
        assert v_only_comps == ["c"]

    @pytest.mark.unit
    def test_no_vle_components(self):
        m = ConcreteModel()
        m.params = DummyParameterBlock(
            components={
                "b": {
                    "valid_phase_types": PT.liquidPhase,
                },
                "c": {
                    "valid_phase_types": PT.vaporPhase,
                },
                "d": {
                    "valid_phase_types": PT.solidPhase,
                },
            },
            phases={
                "p1": {
                    "type": LiquidPhase,
                    "equation_of_state": DummyEoS,
                },
                "p2": {
                    "type": VaporPhase,
                    "equation_of_state": DummyEoS,
                },
                "p3": {
                    "type": SolidPhase,
                    "equation_of_state": DummyEoS,
                },
            },
            state_definition=self,
            pressure_ref=100000.0,
            temperature_ref=300,
            base_units=self.base_units,
        )

        m.props = m.params.build_state_block([1], defined_state=False)
        with pytest.raises(
            PropertyPackageError,
            match="Phase pair p1-p2 was identified as "
            "being a VLE pair, however there are no components present in both "
            "the vapor and liquid phases simultaneously.",
        ):
            _ = identify_VL_component_list(m.props[1], ("p1", "p2"))


# Property configuration for pure water to use in bubble and dew point tests
configuration = {
    # Specifying components
    "components": {
        "H2O": {
            "type": Component,
            "pressure_sat_comp": NIST,
            "phase_equilibrium_form": {("Vap", "Liq"): log_fugacity},
            "parameter_data": {
                "pressure_crit": (220.6e5, pyunits.Pa),
                "temperature_crit": (647, pyunits.K),
                "omega": 0.344,
                "pressure_sat_comp_coeff": {
                    "A": (3.55959, None),
                    "B": (643.748, pyunits.K),
                    "C": (-198.043, pyunits.K),
                },
            },
        },
    },
    # Specifying phases
    "phases": {
        "Liq": {
            "type": LiquidPhase,
            "equation_of_state": Cubic,
            "equation_of_state_options": {"type": CubicType.PR},
        },
        "Vap": {
            "type": VaporPhase,
            "equation_of_state": Cubic,
            "equation_of_state_options": {"type": CubicType.PR},
        },
    },
    # Set base units of measurement
    "base_units": {
        "time": pyunits.s,
        "length": pyunits.m,
        "mass": pyunits.kg,
        "amount": pyunits.mol,
        "temperature": pyunits.K,
    },
    # Specifying state definition
    "state_definition": FTPx,
    "state_bounds": {
        "flow_mol": (0, 100, 1000, pyunits.mol / pyunits.s),
        "temperature": (273.15, 300, 500, pyunits.K),
        "pressure": (5e4, 1e5, 1e6, pyunits.Pa),
    },
    "pressure_ref": (101325, pyunits.Pa),
    "temperature_ref": (298.15, pyunits.K),
    # Defining phase equilibria
    "phases_in_equilibrium": [("Vap", "Liq")],
    "phase_equilibrium_state": {("Vap", "Liq"): SmoothVLE},
    "bubble_dew_method": LogBubbleDew,
    "parameter_data": {
        "PR_kappa": {
            ("H2O", "H2O"): 0.000,
        }
    },
}


class TestBubbleDewPoints:
    @pytest.fixture
    def model(self):
        m = ConcreteModel()
        m.params = DummyParameterBlock(
            **configuration,
        )

        m.props = m.params.build_state_block([1], defined_state=False)

        return m

    @pytest.mark.unit
    def test_bubble_temperature(self, model):
        # Test bubble temperature at atmospheric pressure
        model.props[1].pressure.set_value(101325)
        Tbub = estimate_Tbub(model.props[1], pyunits.K, ["H2O"], [], "Liq")

        # Expected value = 379.1828 from parameters used
        assert Tbub == pytest.approx(379.1828, rel=1e-6)

    @pytest.mark.unit
    def test_dew_temperature(self, model):
        # Test dew temperature at atmospheric pressure
        model.props[1].pressure.set_value(101325)
        Tdew = estimate_Tdew(model.props[1], pyunits.K, ["H2O"], [], "Liq")

        # Expected value = 379.1828 from parameters used
        assert Tdew == pytest.approx(379.1828, rel=1e-6)

    @pytest.mark.unit
    def test_bubble_pressure(self, model):
        # Test bubble pressure at 100C
        model.props[1].temperature.set_value(373.15)
        Pbub = estimate_Pbub(model.props[1], ["H2O"], [], "Liq")

        # Expected value = 76432.45 from parameters used
        assert Pbub == pytest.approx(76432.45, rel=1e-6)

    @pytest.mark.unit
    def test_dew_pressure(self, model):
        # Test dew pressure at 100C
        model.props[1].temperature.set_value(373.15)
        Pdew = estimate_Pdew(model.props[1], ["H2O"], [], "Liq")

        # Expected value = 76432.45 from parameters used
        assert Pdew == pytest.approx(76432.45, rel=1e-6)
