package app.kodex.data.db

import android.content.Context
import androidx.room3.Database
import androidx.room3.Room
import androidx.room3.RoomDatabase

/**
 * The device's copy of the catalog, its reading positions and its downloads. Version 1 is the
 * first; a later schema change needs a migration (schemas/ holds the exported versions).
 */
@Database(
    entities = [
        LibraryEntity::class, SeriesEntity::class, BookEntity::class, CollectionEntity::class,
        CollectionBookEntity::class, ProgressEntity::class, OutboxEntity::class, SyncStateEntity::class,
        DownloadEntity::class,
    ],
    version = 1,
    exportSchema = true,
)
abstract class KodexDatabase : RoomDatabase() {
    abstract fun catalog(): CatalogDao

    abstract fun state(): StateDao

    abstract fun downloads(): DownloadDao

    companion object {
        fun build(context: Context): KodexDatabase =
            Room.databaseBuilder(context.applicationContext, KodexDatabase::class.java, "kodex.db").build()

        fun inMemory(context: Context): KodexDatabase =
            Room.inMemoryDatabaseBuilder(context.applicationContext, KodexDatabase::class.java).build()
    }
}
