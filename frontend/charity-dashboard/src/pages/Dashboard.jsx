import Navbar from "../components/Navbar"
import FoodCard from "../components/FoodCard"

function Dashboard(){

  return (
    <div>

      <Navbar />

      <h1>Available Food Near You blah</h1>

      <div className="food-grid">

        <FoodCard
          name="Sourdough Bread"
          vendor="Golden Crust Bakery"
          distance="1.2km"
          quantity="8 loaves"
        />

        <FoodCard
          name="Mixed Fruit Box"
          vendor="FreshMart Supermarket"
          distance="2.8km"
          quantity="5 boxes"
        />

      </div>

    </div>
  )

}

export default Dashboard