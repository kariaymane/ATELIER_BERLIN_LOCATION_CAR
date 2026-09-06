package com.example

import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.DirectionsCar
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import com.example.ui.components.FleetCountCard
import com.example.ui.components.OperationalStatCard
import com.example.ui.theme.MyApplicationTheme
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [36])
class DashboardComponentsTest {
  @get:Rule val composeTestRule = createComposeRule()

  @Test
  fun operational_stat_card_displays_its_values() {
    composeTestRule.setContent {
      MyApplicationTheme {
        OperationalStatCard(label = "Aujourd'hui", value = "12", subtitle = "réservations")
      }
    }
    composeTestRule.onNodeWithText("Aujourd'hui").assertIsDisplayed()
    composeTestRule.onNodeWithText("12").assertIsDisplayed()
    composeTestRule.onNodeWithText("réservations").assertIsDisplayed()
  }

  @Test
  fun fleet_count_card_displays_its_count() {
    composeTestRule.setContent {
      MyApplicationTheme {
        FleetCountCard(title = "Prêts à louer", count = 65, icon = Icons.Default.DirectionsCar)
      }
    }
    composeTestRule.onNodeWithText("Prêts à louer").assertIsDisplayed()
    composeTestRule.onNodeWithText("65").assertIsDisplayed()
  }
}
